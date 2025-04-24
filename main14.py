import os
import sqlite3
import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from datetime import datetime
import plotly.express as px

# Database setup
DB_NAME = "drug_data.db"

# Connect to SQLite database
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

conn = get_connection()

# Initialize PaymentMethods table with sample data if not already present
def initialize_payment_methods():
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM PaymentMethods")
    if c.fetchone()[0] == 0:
        methods = [
            ("COD", "Cash on Delivery"),
            ("UPI", "Unified Payments Interface"),
            ("Net Banking", "Internet Banking"),
            ("Studd", "Student Discount Payment (Placeholder)")
        ]
        c.executemany("INSERT INTO PaymentMethods (MethodName, Description) VALUES (?, ?)", methods)
        conn.commit()

initialize_payment_methods()

# Function to fetch payment methods
@st.cache_data(ttl=300)
def fetch_payment_methods():
    c = conn.cursor()
    c.execute("SELECT PaymentMethodID, MethodName FROM PaymentMethods")
    methods = c.fetchall()
    return {method[1]: method[0] for method in methods}

# Function to add pharmacy payment method
def add_pharmacy_payment(pharmacy_id, payment_method_id, account_details, is_default=False):
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO PharmacyPayments (PharmacyID, PaymentMethodID, AccountDetails, IsDefault)
            VALUES (?, ?, ?, ?)
        """, (pharmacy_id, payment_method_id, account_details, is_default))
        conn.commit()
        return True, "Payment method added successfully!"
    except Exception as e:
        return False, f"Error adding payment method: {str(e)}"

# Function to create a payment for restock
def create_restock_payment(pharmacy_id, supplier_id, amount, payment_method_id, restock_id, status="Pending", notes=None):
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO Payments (PharmacyID, SupplierID, Amount, PaymentMethodID, Status, Notes, TransactionReference)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (pharmacy_id, supplier_id, amount, payment_method_id, status, notes, f"Restock-{restock_id}"))
        payment_id = c.lastrowid
        # Update RestockOrder payment status
        c.execute("UPDATE RestockOrders SET PaymentStatus = ? WHERE RestockID = ?", (status, restock_id))
        conn.commit()
        
        # Notify supplier
        c.execute("""
            INSERT INTO SupplierNotifications (SupplierID, Title, Message, RelatedEntityType, RelatedEntityID)
            VALUES (?, ?, ?, ?, ?)
        """, (supplier_id, "New Restock Payment", f"Payment of ${amount} initiated for Restock ID {restock_id}", "Payment", payment_id))
        conn.commit()
        
        return True, "Payment created successfully!", payment_id
    except Exception as e:
        return False, f"Error creating payment: {str(e)}", None

# Function to generate PDF report
def generate_pdf_report(data, filter_type, filter_value):
    pdf_file = f"report_{filter_value}.pdf"
    c = canvas.Canvas(pdf_file, pagesize=letter)
    c.drawString(100, 750, f"Report for {filter_type}: {filter_value}")
    c.drawString(100, 730, "Details:")
    y_position = 710
    for row in data:
        c.drawString(100, y_position, str(row))
        y_position -= 20
    c.save()
    with open(pdf_file, "rb") as f:
        st.download_button("📥 Download PDF Report", f, file_name=pdf_file, mime="application/pdf")
    os.remove(pdf_file)

# Function to generate reports with filtering
def generate_reports():
    st.subheader("Generate PDF Report")
    report_type = st.selectbox("Select Report Type", ["Drugs", "Customers", "Orders", "Low Stock", "Suppliers", "Tickets", "Restock Orders", "Payments"])
    with st.expander("Filter Options", expanded=False):
        filter_type = st.selectbox("Filter by", ["None"] + {
            "Drugs": ["ID", "Name", "Price Range", "Discontinued"],
            "Customers": ["Name", "Email", "State"],
            "Orders": ["Name", "Item", "Date Range"],
            "Low Stock": ["None"],
            "Suppliers": ["ID", "Name", "Email"],
            "Tickets": ["ID", "Status", "Date Range"],
            "Restock Orders": ["ID", "Supplier ID", "Drug ID", "Status"],
            "Payments": ["PharmacyID", "SupplierID", "Status", "Date Range"]
        }[report_type])
        
        filter_query = ""
        params = []
        
        if report_type == "Payments" and filter_type != "None":
            if filter_type == "PharmacyID":
                pharmacy_id = st.text_input("Enter Pharmacy ID")
                if pharmacy_id:
                    filter_query = "PharmacyID = ?"
                    params.append(pharmacy_id)
            elif filter_type == "SupplierID":
                supplier_id = st.text_input("Enter Supplier ID")
                if supplier_id:
                    filter_query = "SupplierID = ?"
                    params.append(supplier_id)
            elif filter_type == "Status":
                status = st.selectbox("Select Status", ["Pending", "Completed", "Failed"])
                if status:
                    filter_query = "Status = ?"
                    params.append(status)
            elif filter_type == "Date Range":
                start_date = st.date_input("Start Date")
                end_date = st.date_input("End Date")
                filter_query = "PaymentDate BETWEEN ? AND ?"
                params.extend([start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")])

        # Add filtering logic for other report types (unchanged for brevity)
        # ... (previous filtering logic remains the same)

    if st.button("Generate Report"):
        c = conn.cursor()
        if report_type == "Payments":
            query = "SELECT * FROM Payments" + (" WHERE " + filter_query if filter_query else "")
            c.execute(query, tuple(params))
            df = pd.DataFrame(c.fetchall(), columns=[desc[0] for desc in c.description])
            filter_value = filter_type if filter_type == "None" else f"{filter_type}: {params[0] if params else 'All'}"
        # ... (previous report generation logic remains the same)
        
        if not df.empty:
            st.dataframe(df)
            generate_pdf_report(df.values.tolist(), report_type, filter_value)
        else:
            st.warning("No data available to generate the report.")

# Function to logout
def logout():
    for key in ["retail_pharmacist_logged_in", "supplier_logged_in"]:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

# Function to check low stock
@st.cache_data(ttl=3600)
def check_low_stock():
    c = conn.cursor()
    c.execute("SELECT * FROM Drugs WHERE stock_no <= 100")
    low_stock_items = c.fetchall()
    column_names = [description[0] for description in c.description]
    return low_stock_items, column_names

# Function to create a restock order and ticket
def create_restock_order(supplier_id, drug_id, quantity, pharmacy_id):
    try:
        c = conn.cursor()
        c.execute("INSERT INTO RestockOrders (SupplierID, DrugID, Quantity, Status) VALUES (?, ?, ?, 'Pending')", 
                  (supplier_id, drug_id, quantity))
        restock_id = c.lastrowid
        c.execute("INSERT INTO Tickets (RestockID, SupplierID, Status) VALUES (?, ?, 'Open')", 
                  (restock_id, supplier_id))
        conn.commit()
        fetch_all_tickets.clear()
        fetch_all_restock_orders.clear()
        check_low_stock.clear()
        return True, "Restock order and ticket created successfully!", restock_id, drug_id
    except Exception as e:
        return False, f"Error creating restock order: {str(e)}", None, None

# Function to update drug stock to 200
def update_drug_stock(drug_id):
    try:
        c = conn.cursor()
        c.execute("UPDATE Drugs SET stock_no = 200 WHERE D_id = ?", (drug_id,))
        c.execute("UPDATE RestockOrders SET Status = 'Delivered', PaymentStatus = 'Completed' WHERE DrugID = ?", (drug_id,))
        c.execute("UPDATE Tickets SET Status = 'Closed' WHERE RestockID IN (SELECT RestockID FROM RestockOrders WHERE DrugID = ?)", (drug_id,))
        conn.commit()
        fetch_all_drugs.clear()
        fetch_all_tickets.clear()
        fetch_all_restock_orders.clear()
        check_low_stock.clear()
        return True, "Stock updated to 200 and restock status updated!"
    except Exception as e:
        return False, f"Error updating stock: {str(e)}"

# Cache expensive database queries
@st.cache_data(ttl=300)
def fetch_all_drugs():
    c = conn.cursor()
    c.execute("SELECT * FROM Drugs")
    data = c.fetchall()
    column_names = [description[0] for description in c.description]
    return pd.DataFrame(data, columns=column_names)

@st.cache_data(ttl=300)
def fetch_all_customers():
    c = conn.cursor()
    c.execute("SELECT * FROM Customers")
    data = c.fetchall()
    column_names = [description[0] for description in c.description]
    return pd.DataFrame(data, columns=column_names)

@st.cache_data(ttl=300)
def fetch_all_orders():
    c = conn.cursor()
    c.execute("SELECT O_id, O_Name, O_Items, O_Qty, O_Date FROM Orders")
    orders = c.fetchall()
    column_names = [description[0] for description in c.description]
    return pd.DataFrame(orders, columns=column_names)

@st.cache_data(ttl=300)
def fetch_all_tickets():
    c = conn.cursor()
    c.execute("SELECT * FROM Tickets")
    tickets = c.fetchall()
    column_names = [description[0] for description in c.description]
    return pd.DataFrame(tickets, columns=column_names)

@st.cache_data(ttl=300)
def fetch_all_restock_orders():
    c = conn.cursor()
    c.execute("SELECT * FROM RestockOrders")
    restock_orders = c.fetchall()
    column_names = [description[0] for description in c.description]
    return pd.DataFrame(restock_orders, columns=column_names)

@st.cache_data(ttl=300)
def fetch_all_suppliers():
    c = conn.cursor()
    c.execute("SELECT * FROM Suppliers")
    suppliers = c.fetchall()
    column_names = [description[0] for description in c.description]
    return pd.DataFrame(suppliers, columns=column_names)

@st.cache_data(ttl=300)
def fetch_all_payments():
    c = conn.cursor()
    c.execute("SELECT * FROM Payments")
    payments = c.fetchall()
    column_names = [description[0] for description in c.description]
    return pd.DataFrame(payments, columns=column_names)

@st.cache_data(ttl=300)
def fetch_supplier_notifications(supplier_id):
    c = conn.cursor()
    c.execute("SELECT * FROM SupplierNotifications WHERE SupplierID = ? ORDER BY CreatedAt DESC", (supplier_id,))
    notifications = c.fetchall()
    column_names = [description[0] for description in c.description]
    return pd.DataFrame(notifications, columns=column_names)

# Function to update stock when order is placed
def update_stock_after_order(drug_name, quantity):
    try:
        c = conn.cursor()
        c.execute("SELECT D_id, stock_no FROM Drugs WHERE D_Name = ?", (drug_name,))
        drug = c.fetchone()
        if not drug:
            return False, "Drug not found."
        drug_id, current_stock = drug
        if current_stock < quantity:
            return False, f"Not enough stock available. Current stock: {current_stock}"
        c.execute("UPDATE Drugs SET stock_no = stock_no - ? WHERE D_id = ?", (quantity, drug_id))
        conn.commit()
        fetch_all_drugs.clear()
        return True, "Stock updated successfully."
    except Exception as e:
        return False, f"Error updating stock: {str(e)}"

# Function to add a new customer
def add_new_customer(name, password, email, state, number):
    try:
        c = conn.cursor()
        c.execute("INSERT INTO Customers (C_Name, C_Password, C_Email, C_State, C_Number) VALUES (?, ?, ?, ?, ?)", 
                  (name, password, email, state, number))
        conn.commit()
        fetch_all_customers.clear()
        return True, "Customer added successfully!"
    except sqlite3.IntegrityError:
        return False, "Error: Email already exists."
    except Exception as e:
        return False, f"Error: {str(e)}"

# Function to add a new order with payment
def add_new_order(pharmacy_id, name, items, quantity, payment_method):
    try:
        stock_success, stock_message = update_stock_after_order(items, quantity)
        if not stock_success:
            return False, stock_message

        c = conn.cursor()
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO Orders (O_Name, O_Items, O_Qty, O_Date) VALUES (?, ?, ?, ?)",
                  (name, items, quantity, current_date))
        order_id = c.lastrowid
        
        # Get drug price for payment calculation
        c.execute("SELECT D_Price FROM Drugs WHERE D_Name = ?", (items,))
        drug_price = c.fetchone()[0]
        amount = drug_price * quantity
        
        payment_methods = fetch_payment_methods()
        payment_method_id = payment_methods.get(payment_method)
        success, message, payment_id = create_payment(pharmacy_id, 1, amount, payment_method_id, "Pending", f"Order ID: {order_id}")
        
        if success:
            conn.commit()
            fetch_all_orders.clear()
            fetch_all_payments.clear()
            return True, "Order added successfully with payment!"
        else:
            return False, message
    except Exception as e:
        return False, f"Error: {str(e)}"

# Function to add a new customer form
def add_customer_form():
    st.subheader("Add New Customer")
    with st.form("new_customer_form"):
        name = st.text_input("Customer Name")
        password = st.text_input("Password", type="password")
        email = st.text_input("Email")
        state = st.text_input("State")
        number = st.text_input("Phone Number")
        submitted = st.form_submit_button("Add Customer")
        
        if submitted:
            success, message = add_new_customer(name, password, email, state, number)
            if success:
                st.success(message)
            else:
                st.error(message)

# Function to add a new order form with payment options
def add_order_form(pharmacy_id):
    st.subheader("Add New Order")
    with st.form("new_order_form"):
        name = st.text_input("Order Name")
        items = st.selectbox("Select Drug", fetch_all_drugs()['D_Name'].tolist())
        quantity = st.number_input("Quantity", min_value=1, value=1)
        payment_method = st.selectbox("Payment Method", ["COD", "UPI", "Net Banking", "Studd"])
        submitted = st.form_submit_button("Add Order")
        
        if submitted:
            success, message = add_new_order(pharmacy_id, name, items, quantity, payment_method)
            if success:
                st.success(message)
            else:
                st.error(message)

# Function to add a new retail pharmacist
def add_new_retail_pharmacist(name, email, password, address, phone_number, billing_address=None, tax_id=None):
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO RetailPharmacies (PharmacyName, PharmacyEmail, PharmacyPassword, Address, PhoneNumber, 
            BillingAddress, TaxID, SupplierID)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """, (name, email, password, address, phone_number, billing_address, tax_id))
        pharmacy_id = c.lastrowid
        conn.commit()
        # Add default payment method
        payment_methods = fetch_payment_methods()
        add_pharmacy_payment(pharmacy_id, payment_methods["COD"], "Cash on delivery", True)
        return True, "Retail Pharmacist account created successfully!", pharmacy_id
    except sqlite3.IntegrityError:
        return False, "Error: Email already exists.", None
    except Exception as e:
        return False, f"Error: {str(e)}", None

# Function to add a new supplier
def add_new_supplier(name, email, contact_number, address, password):
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO Suppliers (SupplierName, ContactEmail, ContactNumber, Address, SupplierPassword)
            VALUES (?, ?, ?, ?, ?)
        """, (name, email, contact_number, address, password))
        supplier_id = c.lastrowid
        conn.commit()
        fetch_all_suppliers.clear()
        return True, "Supplier account created successfully!", supplier_id
    except sqlite3.IntegrityError:
        return False, "Error: Email already exists.", None
    except Exception as e:
        return False, f"Error: {str(e)}", None

# Signup functions
def signup():
    st.sidebar.header("Sign Up")
    user_type = st.sidebar.radio("Select your role", ["Retail Pharmacist", "Supplier"])
    if user_type == "Retail Pharmacist":
        signup_retail_pharmacist()
    elif user_type == "Supplier":
        signup_supplier()

def signup_retail_pharmacist():
    st.subheader("Sign Up as Retail Pharmacist")
    with st.form("signup_retail_form"):
        pharmacy_name = st.text_input("Pharmacy Name", key="pharmacy_name")
        pharmacy_email = st.text_input("Email Address", key="pharmacy_email")
        pharmacy_password = st.text_input("Password", type="password", key="pharmacy_password")
        confirm_password = st.text_input("Confirm Password", type="password", key="confirm_password")
        address = st.text_input("Address", key="pharmacy_address")
        phone_number = st.text_input("Phone Number", key="pharmacy_phone")
        billing_address = st.text_input("Billing Address", key="billing_address")
        tax_id = st.text_input("Tax ID", key="tax_id")
        submitted = st.form_submit_button("Sign Up")
        
        if submitted:
            if not all([pharmacy_name, pharmacy_email, pharmacy_password, confirm_password, address, phone_number]):
                st.error("All fields are required!")
            elif pharmacy_password != confirm_password:
                st.error("Passwords do not match.")
            elif "@" not in pharmacy_email:
                st.error("Please enter a valid email address.")
            else:
                success, message, pharmacy_id = add_new_retail_pharmacist(
                    pharmacy_name, pharmacy_email, pharmacy_password, address, phone_number, billing_address, tax_id
                )
                if success:
                    st.session_state.retail_pharmacist_logged_in = True
                    st.session_state.pharmacy_id = pharmacy_id
                    st.success("Account created successfully! You are now logged in.")
                    st.rerun()
                else:
                    st.error(message)

def signup_supplier():
    st.subheader("Sign Up as Supplier")
    with st.form("signup_supplier_form"):
        supplier_name = st.text_input("Supplier Name", key="supplier_name")
        contact_email = st.text_input("Contact Email", key="supplier_email")
        contact_number = st.text_input("Contact Number", key="supplier_phone")
        address = st.text_input("Address", key="supplier_address")
        supplier_password = st.text_input("Password", type="password", key="supplier_password")
        confirm_password = st.text_input("Confirm Password", type="password", key="supplier_confirm_password")
        submitted = st.form_submit_button("Sign Up")
        
        if submitted:
            if not all([supplier_name, contact_email, contact_number, address, supplier_password, confirm_password]):
                st.error("All fields are required!")
            elif supplier_password != confirm_password:
                st.error("Passwords do not match.")
            elif "@" not in contact_email:
                st.error("Please enter a valid email address.")
            else:
                success, message, supplier_id = add_new_supplier(
                    supplier_name, contact_email, contact_number, address, supplier_password
                )
                if success:
                    st.session_state.supplier_logged_in = True
                    st.session_state.supplier_id = supplier_id
                    st.success("Account created successfully! You are now logged in.")
                    st.rerun()
                else:
                    st.error(message)

# Function to view drugs
def view_drugs():
    st.subheader("View Drugs")
    with st.expander("Filter Options", expanded=False):
        filter_type = st.selectbox("Filter by", ["None", "ID", "Name", "Price Range", "Discontinued"])
        filter_query = ""
        params = []
        if filter_type == "ID":
            drug_id = st.text_input("Enter Drug ID")
            if drug_id:
                filter_query = "D_id = ?"
                params.append(drug_id)
        elif filter_type == "Name":
            drug_name = st.text_input("Enter Drug Name")
            if drug_name:
                filter_query = "D_Name LIKE ?"
                params.append(f"%{drug_name}%")
        elif filter_type == "Price Range":
            min_price = st.number_input("Minimum Price", min_value=0.0, value=0.0)
            max_price = st.number_input("Maximum Price", min_value=0.0, value=1000.0)
            filter_query = "D_Price BETWEEN ? AND ?"
            params.extend([min_price, max_price])
        elif filter_type == "Discontinued":
            discontinued = st.selectbox("Discontinued Status", ["False", "True"])
            filter_query = "D_IsDiscontinued = ?"
            params.append(discontinued == "True")

    if st.button("Apply Filter"):
        query = "SELECT * FROM Drugs" + (" WHERE " + filter_query if filter_query else "")
        c = conn.cursor()
        c.execute(query, tuple(params))
        data = c.fetchall()
        column_names = [description[0] for description in c.description]
        df = pd.DataFrame(data, columns=column_names)
        st.dataframe(df)
        if not df.empty:
            excel_file = "filtered_drugs.xlsx"
            df.to_excel(excel_file, index=False)
            with open(excel_file, "rb") as f:
                st.download_button(
                    label="Download as Excel",
                    data=f,
                    file_name=excel_file,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            os.remove(excel_file)
    else:
        df = fetch_all_drugs()
        st.dataframe(df)

# Function to fetch suppliers by priority
def fetch_suppliers_by_priority():
    c = conn.cursor()
    c.execute("SELECT SupplierID, SupplierName FROM Suppliers ORDER BY SupplierName DESC")
    return c.fetchall()

# Function to get drug ID from name
def get_drug_id_from_name(drug_name):
    c = conn.cursor()
    c.execute("SELECT D_id FROM Drugs WHERE D_Name = ?", (drug_name,))
    result = c.fetchone()
    return result[0] if result else None

# Function to create a restock ticket form with payment
def restock_ticket_form():
    st.subheader("Create Restock Ticket")
    with st.form("create_ticket_form"):
        low_stock_drugs_df = fetch_all_drugs()[fetch_all_drugs()['stock_no'] <= 100]
        selected_drug_name = st.selectbox("Select Drug (Low Stock Only)", low_stock_drugs_df['D_Name'].tolist())
        selected_drug_id = get_drug_id_from_name(selected_drug_name)
        suppliers = fetch_suppliers_by_priority()
        supplier_options = [f"{s[1]} (ID: {s[0]})" for s in suppliers]
        selected_supplier = st.selectbox("Select Supplier", supplier_options)
        supplier_id = int(selected_supplier.split("ID: ")[1].rstrip(")"))
        quantity = st.number_input("Quantity", min_value=1, value=1)
        reason = st.text_area("Reason for Restock", "Enter reason here...")
        payment_methods = fetch_payment_methods()
        payment_method = st.selectbox("Select Payment Method", ["COD", "UPI", "Net Banking", "Studd"])
        payment_method_id = payment_methods[payment_method]
        submitted = st.form_submit_button("Submit Ticket")
        
        if submitted:
            if selected_drug_id and st.session_state.get("retail_pharmacist_logged_in", False):
                pharmacy_id = st.session_state.pharmacy_id
                success, message, restock_id, drug_id = create_restock_order(supplier_id, selected_drug_id, quantity, pharmacy_id)
                if success:
                    # Get drug price for payment calculation
                    c = conn.cursor()
                    c.execute("SELECT D_Price FROM Drugs WHERE D_id = ?", (drug_id,))
                    drug_price = c.fetchone()[0]
                    amount = drug_price * quantity
                    payment_success, payment_message, payment_id = create_restock_payment(pharmacy_id, supplier_id, amount, payment_method_id, restock_id, "Pending", f"Restock for {selected_drug_name}")
                    if payment_success:
                        st.success(f"Ticket and payment created for {quantity} units of {selected_drug_name} from {selected_supplier.split(' (')[0]}!")
                        st.session_state['last_restock_drug_id'] = drug_id
                        st.session_state['last_supplier_id'] = supplier_id
                    else:
                        st.error(f"Ticket created, but payment failed: {payment_message}")
                else:
                    st.error(message)
            else:
                st.error("Error: Selected drug not found or not logged in as retail pharmacist.")

    if 'last_restock_drug_id' in st.session_state and st.session_state.get("supplier_logged_in", False) and st.session_state.supplier_id == st.session_state['last_supplier_id']:
        if st.button("Send Restocking Items Now"):
            stock_success, stock_message = update_drug_stock(st.session_state['last_restock_drug_id'])
            if stock_success:
                st.success(stock_message)
                st.rerun()
            else:
                st.error(stock_message)
        if stock_success:
            del st.session_state['last_restock_drug_id']
            del st.session_state['last_supplier_id']

# Retail Pharmacist Interface
def retail_pharmacist_interface():
    st.sidebar.subheader("🔑 Retail Pharmacist Login")
    pharmacist_email = st.sidebar.text_input("Email")
    pharmacist_pass = st.sidebar.text_input("Password", type="password")
    
    if st.sidebar.button("Login as Retail Pharmacist"):
        c = conn.cursor()
        c.execute("SELECT PharmacyID, PharmacyPassword FROM RetailPharmacies WHERE PharmacyEmail = ?", (pharmacist_email,))
        pharmacist = c.fetchone()
        if pharmacist and pharmacist[1] == pharmacist_pass:
            st.session_state.retail_pharmacist_logged_in = True
            st.session_state.pharmacy_id = pharmacist[0]
            st.success("Welcome, Retail Pharmacist!")
        else:
            st.sidebar.error("Invalid credentials")
    
    if st.session_state.get("retail_pharmacist_logged_in", False):
        pharmacist_menu = [
            "📊 Dashboard", 
            "👥 View Customers", 
            "➕ Add New Customer", 
            "💊 View Drugs", 
            "📦 View Orders", 
            "➕ Add New Order", 
            "📄 Generate PDF Report", 
            "🚚 View Suppliers", 
            "📋 View Tickets", 
            "⚠️ Low Stock", 
            "💳 Manage Payments"
        ]
        pharmacist_choice = st.sidebar.selectbox("Retail Pharmacist Menu", pharmacist_menu)
        
        if pharmacist_choice == "📊 Dashboard":
            st.subheader("📊 Retail Pharmacist Dashboard")
            
            # Fetch data
            drugs_df = fetch_all_drugs()
            customers_df = fetch_all_customers()
            suppliers_df = fetch_all_suppliers()
            tickets_df = fetch_all_tickets()
            low_stock_drugs, _ = check_low_stock()
            
            # Metrics Section with Cards
            st.subheader("Overview")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown("📊 **Total Drugs**")
                st.metric("", len(drugs_df), delta_color="off")
            with col2:
                st.markdown("👥 **Total Customers**")
                st.metric("", len(customers_df), delta_color="off")
            with col3:
                st.markdown("🚚 **Total Suppliers**")
                st.metric("", len(suppliers_df), delta_color="off")
            with col4:
                st.markdown("⚠️ **Low Stock Alerts**")
                st.metric("", len(low_stock_drugs), delta_color="inverse")
            
            # Cards for Key Sections
            st.subheader("Quick Access")
            card1, card2, card3 = st.columns(3)
            with card1:
                st.markdown("💊 **Drugs**")
                st.info(f"{len(drugs_df)} drugs available.")
                if st.button("View All Drugs", key="view_drugs"):
                    view_drugs()
            with card2:
                st.markdown("📦 **Orders**")
                st.info(f"{len(fetch_all_orders())} orders placed.")
                if st.button("View All Orders", key="view_orders"):
                    st.dataframe(fetch_all_orders())
            with card3:
                st.markdown("📋 **Tickets**")
                st.info(f"{len(tickets_df)} tickets created.")
                if st.button("View All Tickets", key="view_tickets"):
                    st.dataframe(tickets_df)
            
            # Recent Tickets Table
            st.subheader("📋 Recent Tickets")
            st.dataframe(tickets_df[['TicketID', 'RestockID', 'SupplierID', 'Status']].head(5))
            
            # Low Stock Alert
            if low_stock_drugs:
                st.subheader("⚠️ Low Stock Alert")
                low_stock_df = pd.DataFrame(low_stock_drugs, columns=["Drug ID", "Name", "Stock"])
                st.dataframe(low_stock_df.style.highlight_between(left=0, right=50, color="red"))
                st.warning(f"⚠️ {len(low_stock_drugs)} drugs have low stock!")
            else:
                st.info("No low stock items detected.")
        
        elif pharmacist_choice == "👥 View Customers":
            st.subheader("👥 Customer Data")
            st.dataframe(fetch_all_customers())
        
        elif pharmacist_choice == "➕ Add New Customer":
            add_customer_form()
        
        elif pharmacist_choice == "💊 View Drugs":
            view_drugs()
        
        elif pharmacist_choice == "📦 View Orders":
            st.subheader("📦 Order Data")
            st.dataframe(fetch_all_orders())
        
        elif pharmacist_choice == "➕ Add New Order":
            add_order_form(st.session_state.pharmacy_id)
        
        elif pharmacist_choice == "📄 Generate PDF Report":
            generate_reports()
        
        elif pharmacist_choice == "🚚 View Suppliers":
            st.subheader("🚚 View Suppliers")
            st.dataframe(fetch_all_suppliers())
        
        elif pharmacist_choice == "📋 View Tickets":
            st.subheader("📋 View Tickets")
            st.dataframe(fetch_all_tickets())
        
        elif pharmacist_choice == "⚠️ Low Stock":
            st.subheader("⚠️ Low Stock Alert")
            low_stock_drugs, column_names = check_low_stock()
            if low_stock_drugs:
                low_stock_df = pd.DataFrame(low_stock_drugs, columns=column_names)
                st.dataframe(low_stock_df.style.highlight_between(left=0, right=50, color="red"))
                st.warning(f"⚠️ {len(low_stock_drugs)} drugs have low stock!")
                restock_ticket_form()
            else:
                st.info("No low stock items detected.")
        
        elif pharmacist_choice == "💳 Manage Payments":
            st.subheader("💳 Manage Payment Methods")
            payment_methods = fetch_payment_methods()
            method_options = list(payment_methods.keys())
            with st.form("add_payment_form"):
                selected_method = st.selectbox("Select Payment Method", method_options)
                account_details = st.text_input("Account Details (e.g., UPI ID, Bank Account)")
                is_default = st.checkbox("Set as Default")
                submitted = st.form_submit_button("Add Payment Method")
                if submitted:
                    success, message = add_pharmacy_payment(st.session_state.pharmacy_id, payment_methods[selected_method], account_details, is_default)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
            st.subheader("Current Payment Methods")
            c = conn.cursor()
            c.execute("""
                SELECT pm.MethodName, pp.AccountDetails, pp.IsDefault 
                FROM PharmacyPayments pp 
                JOIN PaymentMethods pm ON pp.PaymentMethodID = pm.PaymentMethodID 
                WHERE pp.PharmacyID = ?
            """, (st.session_state.pharmacy_id,))
            payment_data = c.fetchall()
            if payment_data:
                df = pd.DataFrame(payment_data, columns=["Method", "Account Details", "Is Default"])
                st.dataframe(df)
            else:
                st.info("No payment methods configured.")

# Supplier Interface
def supplier_interface():
    st.sidebar.subheader("🔑 Supplier Login")
    supplier_email = st.sidebar.text_input("Email")
    supplier_password = st.sidebar.text_input("Password", type="password")
    
    if st.sidebar.button("Login as Supplier"):
        c = conn.cursor()
        c.execute("SELECT SupplierID, SupplierPassword FROM Suppliers WHERE ContactEmail = ?", (supplier_email,))
        supplier = c.fetchone()
        if supplier and supplier[1] == supplier_password:
            st.session_state.supplier_logged_in = True
            st.session_state.supplier_id = supplier[0]
            st.success("Welcome, Supplier!")
        else:
            st.sidebar.error("Invalid credentials")
    
    if st.session_state.get("supplier_logged_in", False):
        supplier_menu = [
            "📊 Dashboard", 
            "💊 View Drugs", 
            "➕ Add New Drug", 
            "📋 Ticket Section", 
            "📦 Check Pharmacies Needing Restocking", 
            "🔔 View Notifications"
        ]
        supplier_choice = st.sidebar.selectbox("Supplier Menu", supplier_menu)
        
        if supplier_choice == "📊 Dashboard":
            st.subheader("📊 Supplier Dashboard")
            
            # Fetch data
            drugs_df = fetch_all_drugs()
            tickets_df = fetch_all_tickets()
            restock_df = fetch_all_restock_orders()
            low_stock_drugs, _ = check_low_stock()
            
            # Metrics Section with Cards
            st.subheader("Overview")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown("📊 **Total Drugs**")
                st.metric("", len(drugs_df), delta_color="off")
            with col2:
                st.markdown("📋 **Total Tickets**")
                st.metric("", len(tickets_df), delta_color="off")
            with col3:
                st.markdown("📦 **Total Restock Orders**")
                st.metric("", len(restock_df), delta_color="off")
            with col4:
                st.markdown("⚠️ **Low Stock Alerts**")
                st.metric("", len(low_stock_drugs), delta_color="inverse")
            
            # Cards for Key Sections
            st.subheader("Quick Access")
            card1, card2, card3 = st.columns(3)
            with card1:
                st.markdown("💊 **Drugs**")
                st.info(f"{len(drugs_df)} drugs available.")
                if st.button("View All Drugs", key="view_drugs_supplier"):
                    view_drugs()
            with card2:
                st.markdown("📋 **Tickets**")
                st.info(f"{len(tickets_df)} tickets created.")
                if st.button("View All Tickets", key="view_tickets_supplier"):
                    st.dataframe(tickets_df)
            with card3:
                st.markdown("📦 **Restock Orders**")
                st.info(f"{len(restock_df)} restock orders pending.")
                if st.button("View All Restock Orders", key="view_restock_orders"):
                    st.dataframe(restock_df)
            
            # Submitted Tickets Table
            st.subheader("📋 Submitted Tickets")
            supplier_tickets = tickets_df[tickets_df['SupplierID'] == st.session_state.supplier_id]
            st.dataframe(supplier_tickets[['TicketID', 'RestockID', 'Status']].head(5))
        
        elif supplier_choice == "💊 View Drugs":
            view_drugs()
        
        elif supplier_choice == "➕ Add New Drug":
            st.subheader("➕ Add New Drug")
            with st.form("new_drug_form"):
                drug_name = st.text_input("Drug Name")
                drug_price = st.number_input("Price", min_value=0.0)
                is_discontinued = st.checkbox("Is Discontinued")
                manufacturer = st.text_input("Manufacturer")
                drug_type = st.text_input("Type")
                pack_size = st.text_input("Pack Size")
                short_comp1 = st.text_input("Short Composition 1")
                short_comp2 = st.text_input("Short Composition 2")
                salt_composition = st.text_input("Salt Composition")
                description = st.text_area("Description")
                side_effects = st.text_area("Side Effects")
                drug_interactions = st.text_area("Drug Interactions")
                stock_no = st.number_input("Stock Number", min_value=0)
                submitted = st.form_submit_button("Add Drug")
                if submitted:
                    c = conn.cursor()
                    c.execute("""
                        INSERT INTO Drugs (D_Name, D_Price, D_IsDiscontinued, D_Manufacturer, D_Type, D_PackSize, 
                        D_ShortComp1, D_ShortComp2, D_SaltComposition, D_Description, D_SideEffects, D_DrugInteractions, stock_no)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (drug_name, drug_price, is_discontinued, manufacturer, drug_type, pack_size, short_comp1, short_comp2, 
                          salt_composition, description, side_effects, drug_interactions, stock_no))
                    conn.commit()
                    fetch_all_drugs.clear()
                    st.success("Drug added successfully!")
        
        elif supplier_choice == "📋 Ticket Section":
            st.subheader("📋 Ticket Section")
            tickets_df = fetch_all_tickets()
            supplier_tickets = tickets_df[tickets_df['SupplierID'] == st.session_state.supplier_id]
            st.dataframe(supplier_tickets)
            for index, ticket in supplier_tickets.iterrows():
                if ticket['Status'] == 'Open':
                    if st.button(f"Send Restocking Items for Ticket {ticket['TicketID']}", key=f"send_{ticket['TicketID']}"):
                        c = conn.cursor()
                        c.execute("SELECT DrugID FROM RestockOrders WHERE RestockID = ?", (ticket['RestockID'],))
                        drug_id = c.fetchone()[0]
                        stock_success, stock_message = update_drug_stock(drug_id)
                        if stock_success:
                            st.success(stock_message)
                            st.rerun()
                        else:
                            st.error(stock_message)
        
        elif supplier_choice == "📦 Check Pharmacies Needing Restocking":
            st.subheader("📦 Pharmacies Needing Restocking")
            c = conn.cursor()
            c.execute("""
                SELECT D.D_Name, D.stock_no, R.RestockID, R.Quantity, R.Status
                FROM Drugs D
                JOIN RestockOrders R ON D.D_id = R.DrugID
                WHERE R.SupplierID = ? AND D.stock_no <= 100
            """, (st.session_state.supplier_id,))
            data = c.fetchall()
            if data:
                df = pd.DataFrame(data, columns=["Drug Name", "Stock Number", "Restock ID", "Quantity", "Status"])
                st.dataframe(df)
            else:
                st.info("No restocking needed currently.")
        
        elif supplier_choice == "🔔 View Notifications":
            st.subheader("🔔 Notifications")
            notifications_df = fetch_supplier_notifications(st.session_state.supplier_id)
            if not notifications_df.empty:
                st.dataframe(notifications_df)
                # Mark as read
                c = conn.cursor()
                c.execute("UPDATE SupplierNotifications SET IsRead = 1 WHERE SupplierID = ? AND IsRead = 0", (st.session_state.supplier_id,))
                conn.commit()
            else:
                st.info("No new notifications.")

# Main app
def main():
    st.title("MediTrack: Your Inventory Companion")
    st.sidebar.header("Login / Sign Up")
    if st.sidebar.button("Sign Up"):
        signup()
    else:
        user_type = st.sidebar.radio("Select your role", ["Retail Pharmacist", "Supplier"])
        if user_type == "Retail Pharmacist":
            retail_pharmacist_interface()
        elif user_type == "Supplier":
            supplier_interface()

    if st.sidebar.button("Exit", on_click=logout):
        pass

if __name__ == "__main__":
    main()