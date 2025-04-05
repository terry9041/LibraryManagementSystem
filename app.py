import sqlite3
from datetime import datetime, timedelta
import bcrypt
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Connect to the database
conn = sqlite3.connect('library.db')
print("Opened database successfully\n")

# Get admin password from environment variable
admin_password = os.getenv("ADMIN_PASSWORD")
if not admin_password:
    print("WARNING: Admin password not found in environment variables")
    admin_password = "LibraryAdmin123"  # Fallback for development only

# Hash the admin password once at startup
ADMIN_HASH = bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt())

# Error handling utility functions
def handle_input_error(message):
    print(f"\nINPUT ERROR: {message}")
    input("Press Enter to return to menu...")
    return None

def handle_critical_error(message):
    print(f"\nCRITICAL ERROR: {message}")
    print("The application must exit.")
    input("Press Enter to exit...")
    conn.close()
    exit(1)

# Function to safely get integer input
def safe_int_input(prompt):
    try:
        return int(input(prompt))
    except ValueError:
        handle_input_error("Please enter a valid number")
        return None


# Function to find an item
def find_item(title):
    with conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT i.ItemID, i.Title, i.BorrowingStatus, i.Location, GROUP_CONCAT(a.FirstName || ' ' || a.LastName) as Authors, i.ReferenceOnly
            FROM Item i
            LEFT JOIN Item_Author ia ON i.ItemID = ia.ItemID
            LEFT JOIN Author a ON ia.AuthorID = a.AuthorID
            WHERE i.Title LIKE ?
            GROUP BY i.ItemID
        """, (f'%{title}%',))
        items = cur.fetchall()
        if items:
            for item in items:
                print(f"ID: {item[0]}, Title: {item[1]}, Status: {item[2]}, Location: {item[3]}")
                if item[4]:  # Check if there are any authors
                    print(f"Author(s): {item[4]}")
                if item[5]:  # Check if it's reference-only
                    print("** REFERENCE ONLY - Not available for borrowing **")
                print("-" * 40)
        else:
            print("No items found with that title.")
# Function to borrow an item
def borrow_item(member_id, item_id):
    try:
        with conn:
            cur = conn.cursor()
            
            # Check if the member exists and is active
            cur.execute("SELECT Status FROM Member WHERE MemberID = ?", (member_id,))
            member_status = cur.fetchone()
            
            if not member_status:
                return handle_input_error(f"Member with ID {member_id} not found")
                
            if member_status[0] != 'Active':
                return handle_input_error(f"Member {member_id} is inactive and cannot borrow items")
            
            # Check if member has outstanding fines
            cur.execute("SELECT TotalFine FROM Fine WHERE MemberID = ?", (member_id,))
            fine_record = cur.fetchone()
            if fine_record and fine_record[0] > 0:
                return handle_input_error(f"Member {member_id} has an outstanding fine of ${fine_record[0]:.2f} and cannot borrow items until it is paid")
            
            # Check if the item exists, is available, and is not reference-only
            cur.execute("SELECT BorrowingStatus, ReferenceOnly FROM Item WHERE ItemID = ?", (item_id,))
            item_info = cur.fetchone()
            
            if not item_info:
                return handle_input_error(f"Item with ID {item_id} not found")
                
            status, reference_only = item_info
            
            if reference_only:
                return handle_input_error(f"Item {item_id} is reference-only and cannot be borrowed")
                
            if status == 'Borrowed':
                return handle_input_error(f"Item {item_id} is already borrowed by another member")
            
            # Proceed with borrowing
            borrow_date = datetime.now().strftime('%Y-%m-%d')
            due_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
            
            cur.execute("INSERT INTO Borrowing (MemberID, ItemID, BorrowDate, DueDate) VALUES (?, ?, ?, ?)", 
                        (member_id, item_id, borrow_date, due_date))
            
            print(f"\nSUCCESS: Item {item_id} borrowed successfully by Member {member_id}. Due: {due_date}")
            return True
            
    except sqlite3.Error as e:
        handle_critical_error(f"Database error while borrowing item: {e}")

# Function to return an item
def return_item(borrowing_id):
    try:
        with conn:
            cur = conn.cursor()
            return_date = datetime.now().strftime('%Y-%m-%d')
            cur.execute("UPDATE Borrowing SET ReturnDate = ? WHERE BorrowingID = ? AND ReturnDate IS NULL",
                        (return_date, borrowing_id))
            
            if cur.rowcount > 0:
                print(f"\nSUCCESS: Item returned successfully. Checking for fines...")
                
                # Check if a fine was applied
                cur.execute("SELECT FineAmount, MemberID FROM Borrowing WHERE BorrowingID = ?", (borrowing_id,))
                result = cur.fetchone()
                if result:
                    fine_amount, member_id = result
                    if fine_amount > 0:
                        print(f"NOTICE: A fine of ${fine_amount:.2f} has been added to your account.")
                        
                        # Update the Fine table
                        cur.execute("SELECT TotalFine FROM Fine WHERE MemberID = ?", (member_id,))
                        fine_record = cur.fetchone()
                        if fine_record:
                            cur.execute("UPDATE Fine SET TotalFine = TotalFine + ? WHERE MemberID = ?", (fine_amount, member_id))
                        else:
                            cur.execute("INSERT INTO Fine (MemberID, TotalFine) VALUES (?, ?)", (member_id, fine_amount))
                    else:
                        print("NOTICE: No fines were applied.")
                return True
            else:
                return handle_input_error("Borrowing ID not found or item already returned")
    except sqlite3.Error as e:
        handle_critical_error(f"Database error while returning item: {e}")

def donate_item(member_id, title, type, genre=None, publication_date=None, location=None, isbn=None, reference_only=False):
    try:
        with conn:
            cur = conn.cursor()
            
            # Check if member exists and is active
            cur.execute("SELECT Status FROM Member WHERE MemberID = ?", (member_id,))
            member_status = cur.fetchone()
            
            if not member_status:
                return handle_input_error(f"Member with ID {member_id} not found")
                
            if member_status[0] != 'Active':
                return handle_input_error(f"Member {member_id} is inactive and cannot donate items")
            
            # Validate title
            if not title or len(title.strip()) == 0:
                return handle_input_error("Title cannot be empty")
            
            # Validate item type
            valid_types = ('Print Book', 'Online Book', 'Magazine', 'Journal', 'CD', 'Record')
            if type not in valid_types:
                valid_types_str = ", ".join(f"'{t}'" for t in valid_types)
                return handle_input_error(f"Invalid item type. Type must be one of: {valid_types_str}")
            
            # Check for existing ISBN before attempting insert
            if isbn:
                cur.execute("SELECT Title FROM Item WHERE ISBN = ?", (isbn,))
                existing_item = cur.fetchone()
                if existing_item:
                    print(f"\nNOTICE: An item with ISBN {isbn} already exists in our system.")
                    print(f"Existing title: {existing_item[0]}")
                    confirm = input("Do you still want to donate this item? (yes/no): ").lower()
                    if confirm != 'yes':
                        print("Donation cancelled.")
                        return False
                    print("Proceeding with donation of duplicate ISBN item...")
            
            # Insert the item with reference_only flag
            cur.execute("""
                INSERT INTO Item (Title, Type, Genre, PublicationDate, Location, ISBN, ReferenceOnly) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (title, type, genre, publication_date, location, isbn, 1 if reference_only else 0))
                
            item_id = cur.lastrowid
            donation_date = datetime.now().strftime('%Y-%m-%d')
            
            cur.execute("INSERT INTO Donation (MemberID, ItemID, DonationDate) VALUES (?, ?, ?)",
                        (member_id, item_id, donation_date))
                        
            print(f"\nSUCCESS: Item '{title}' donated successfully. Pending approval.")
            if reference_only:
                print("NOTE: This item is marked as reference-only and will not be available for borrowing.")
            return True
            
    except sqlite3.IntegrityError as e:
        error_msg = str(e)
        if 'CHECK constraint failed' in error_msg:
            return handle_input_error(f"Invalid item information: {error_msg}")
        else:
            return handle_input_error(f"Problem donating the item: {error_msg}")
    except sqlite3.Error as e:
        handle_critical_error(f"Database error while donating item: {e}")


def cancel_event_registration(member_id, event_id):
    try:
        with conn:
            cur = conn.cursor()
            
            # Check if event exists
            cur.execute("SELECT Name, Date FROM Event WHERE EventID = ?", (event_id,))
            event_info = cur.fetchone()
            if not event_info:
                return handle_input_error(f"Event with ID {event_id} not found")
                
            event_name, event_date = event_info
            
            # Check if event date is in the past
            event_datetime = datetime.strptime(event_date, '%Y-%m-%d')
            if event_datetime < datetime.now():
                return handle_input_error(f"Cannot cancel registration for event '{event_name}' as it has already occurred")
            
            # Check if member is registered for this event
            cur.execute("SELECT COUNT(*) FROM Event_Member WHERE EventID = ? AND MemberID = ?", (event_id, member_id))
            if cur.fetchone()[0] == 0:
                return handle_input_error(f"You are not registered for event '{event_name}'")
            
            # Cancel the registration
            cur.execute("DELETE FROM Event_Member WHERE EventID = ? AND MemberID = ?", (event_id, member_id))
            
            if cur.rowcount > 0:
                # Update the current attendees count
                cur.execute("UPDATE Event SET CurrentAttendees = CurrentAttendees - 1 WHERE EventID = ?", (event_id,))
                
                print(f"\nSUCCESS: Cancelled registration for Event '{event_name}'.")
                return True
            else:
                return handle_input_error(f"Failed to cancel registration for event '{event_name}'")
            
    except sqlite3.Error as e:
        handle_critical_error(f"Database error while cancelling event registration: {e}")

# Function to find an event
def find_event(event_name):
    with conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.EventID, e.Name, e.Date, e.Time, sr.RoomName, 
                   e.MaxCapacity, e.CurrentAttendees, e.Description, e.RecommendedAudience
            FROM Event e
            JOIN SocialRoom sr ON e.SocialRoomID = sr.SocialRoomID
            WHERE e.Name LIKE ?
        """, (f'%{event_name}%',))
        events = cur.fetchall()
        if events:
            for event in events:
                print(f"ID: {event[0]}, Name: {event[1]}")
                print(f"Date: {event[2]}, Time: {event[3]}")
                print(f"Location: {event[4]}")
                print(f"Capacity: {event[5]}, Current Attendees: {event[6]} ({event[5] - event[6]} spots left)")
                if event[7]: 
                    print(f"Description: {event[7]}")
                if event[8]: 
                    print(f"Recommended for: {event[8]}")
                print("-" * 40)
        else:
            print("No events found with that name.")

def register_event(member_id, event_id):
    try:
        with conn:
            cur = conn.cursor()
            
            # Check if event exists
            cur.execute("SELECT Name, MaxCapacity, CurrentAttendees, Date FROM Event WHERE EventID = ?", (event_id,))
            event_info = cur.fetchone()
            if not event_info:
                return handle_input_error(f"Event with ID {event_id} not found")
            
            event_name, max_capacity, current_attendees, event_date = event_info
            
            # Check if event is already at capacity
            if current_attendees >= max_capacity:
                return handle_input_error(f"Sorry, event '{event_name}' is already at full capacity ({max_capacity} attendees)")
            
            # Check if event date is in the past
            event_datetime = datetime.strptime(event_date, '%Y-%m-%d')
            if event_datetime < datetime.now():
                return handle_input_error(f"Cannot register for event '{event_name}' as it has already occurred")
            
            # Check if member exists
            cur.execute("SELECT COUNT(*) FROM Member WHERE MemberID = ?", (member_id,))
            if cur.fetchone()[0] == 0:
                return handle_input_error(f"Member with ID {member_id} not found")
            
            # Check if member is active
            cur.execute("SELECT Status FROM Member WHERE MemberID = ?", (member_id,))
            if cur.fetchone()[0] != 'Active':
                return handle_input_error(f"Member {member_id} is inactive and cannot register for events")
            
            # Check if member is already registered
            cur.execute("SELECT COUNT(*) FROM Event_Member WHERE EventID = ? AND MemberID = ?", (event_id, member_id))
            if cur.fetchone()[0] > 0:
                return handle_input_error(f"You are already registered for event '{event_name}'")
            
            # Register for the event
            reg_date = datetime.now().strftime('%Y-%m-%d')
            cur.execute("INSERT INTO Event_Member (EventID, MemberID, RegistrationDate) VALUES (?, ?, ?)",
                        (event_id, member_id, reg_date))
            
            # Update the current attendees count
            cur.execute("UPDATE Event SET CurrentAttendees = CurrentAttendees + 1 WHERE EventID = ?", (event_id,))
            
            print(f"\nSUCCESS: Registered successfully for Event '{event_name}'.")
            print(f"This event now has {current_attendees + 1} out of {max_capacity} attendees.")
            return True
            
    except sqlite3.IntegrityError:
        return handle_input_error("You are already registered for this event")
    except sqlite3.Error as e:
        handle_critical_error(f"Database error while registering for event: {e}")

# Function to volunteer for an event with improved error handling
def volunteer_event(member_id, event_id, role):
    try:
        with conn:
            cur = conn.cursor()
            
            # Check if event exists
            cur.execute("SELECT COUNT(*) FROM Event WHERE EventID = ?", (event_id,))
            if cur.fetchone()[0] == 0:
                return handle_input_error(f"Event with ID {event_id} not found")
            
            # Check if member exists
            cur.execute("SELECT COUNT(*) FROM Member WHERE MemberID = ?", (member_id,))
            if cur.fetchone()[0] == 0:
                return handle_input_error(f"Member with ID {member_id} not found")
            
            # Check if member is active
            cur.execute("SELECT Status FROM Member WHERE MemberID = ?", (member_id,))
            if cur.fetchone()[0] != 'Active':
                return handle_input_error(f"Member {member_id} is inactive and cannot volunteer for events")
            
            # Validate role
            if not role or len(role.strip()) == 0:
                return handle_input_error("Volunteer role cannot be empty")
            
            vol_date = datetime.now().strftime('%Y-%m-%d')
            cur.execute("INSERT INTO Event_Member_Volunteer (EventID, MemberID, VolunteerRole, VolunteerDate) VALUES (?, ?, ?, ?)",
                        (event_id, member_id, role, vol_date))
            print(f"\nSUCCESS: Volunteered successfully for Event {event_id} as {role}.")
            return True
            
    except sqlite3.IntegrityError:
        return handle_input_error("You are already volunteering for this event")
    except sqlite3.Error as e:
        handle_critical_error(f"Database error while volunteering for event: {e}")

# Function to ask for help from a librarian with improved error handling
def ask_librarian(member_id, question):
    try:
        if not question or len(question.strip()) == 0:
            return handle_input_error("Question cannot be empty")
            
        with conn:
            cur = conn.cursor()
            
            # Check if member exists
            cur.execute("SELECT COUNT(*) FROM Member WHERE MemberID = ?", (member_id,))
            if cur.fetchone()[0] == 0:
                return handle_input_error(f"Member with ID {member_id} not found")
                
            cur.execute("SELECT StaffID, FirstName, Position FROM Staff WHERE Position LIKE '%Librarian%' LIMIT 1")
            librarian = cur.fetchone()
            
            if librarian:
                print(f"\nSUCCESS: Your question has been submitted to {librarian[1]} ({librarian[2]}).")
                print(f"Question: {question}")
                print("A response will be provided shortly.")
                return True
            else:
                return handle_input_error("No librarian is currently available. Please try again later.")
                
    except sqlite3.Error as e:
        handle_critical_error(f"Database error while submitting question: {e}")

def pay_fine(member_id):
    try:
        with conn:
            cur = conn.cursor()
            
            # Check if member has fines
            cur.execute("SELECT TotalFine FROM Fine WHERE MemberID = ?", (member_id,))
            fine_record = cur.fetchone()
            
            if not fine_record or fine_record[0] <= 0:
                print("\nYou have no outstanding fines to pay.")
                return True
            
            fine_amount = fine_record[0]
            print(f"\nYour current fine balance is: ${fine_amount:.2f}")
            
            # Confirm payment
            confirm = input(f"Do you want to pay the full amount of ${fine_amount:.2f}? (yes/no): ").lower()
            if confirm != 'yes':
                print("Payment cancelled.")
                return False
            
            # Admin authentication required for payment processing
            print("\nAdmin authentication required to process payment.")
            admin_code = input("Enter admin code (or type 'cancel' to return): ")
            
            if admin_code.lower() == 'cancel':
                print("Payment cancelled.")
                return False
                
            # Use bcrypt to verify the admin code
            if not bcrypt.checkpw(admin_code.encode(), ADMIN_HASH):
                print("Invalid admin code. Payment could not be processed.")
                return False
            
            # Process payment after successful admin authentication
            cur.execute("UPDATE Fine SET TotalFine = 0 WHERE MemberID = ?", (member_id,))
            
            print(f"\nSUCCESS: Payment of ${fine_amount:.2f} processed successfully.")
            print("Your account is now in good standing and you can borrow items again.")
            return True
            
    except sqlite3.Error as e:
        handle_critical_error(f"Database error while processing payment: {e}")

def main():
    while True:
        try:
            print("\nWelcome to the Library System!")
            print("1. Member Login")
            print("2. Admin Login")
            print("3. Exit")
            
            user_type = input("Enter your choice (1-3): ")
            
            if user_type == '1':
                try:
                    member_id = safe_int_input("Enter your Member ID: ")
                    if member_id is None:
                        continue
                        
                    # Verify member exists
                    with conn:
                        cur = conn.cursor()
                        cur.execute("SELECT COUNT(*) FROM Member WHERE MemberID = ?", (member_id,))
                        if cur.fetchone()[0] == 0:
                            handle_input_error(f"Member with ID {member_id} not found")
                            continue
                    
                    member_menu(member_id)
                except ValueError:
                    handle_input_error("Please enter a valid Member ID (number)")
            
            elif user_type == '2':
                if admin_login():
                    display_all_records()
                    switch = input("Would you like to switch to normal user mode? (yes/no): ").lower()
                    if switch == 'yes':
                        try:
                            member_id = safe_int_input("Enter your Member ID: ")
                            if member_id is not None:
                                member_menu(member_id)
                        except ValueError:
                            handle_input_error("Please enter a valid Member ID (number)")
                    else:
                        print("Exiting admin mode.")
            
            elif user_type == '3':
                print("Exiting the system. Goodbye!")
                break  # Exit the program
            
            else:
                handle_input_error("Invalid choice (must be 1, 2, or 3)")
        
        except Exception as e:
            handle_critical_error(f"Unexpected error: {e}")

# Admin login function with secure bcrypt verification
def admin_login():
    print("\nAdmin Login")
    print("-" * 50)
    
    # Give the user three attempts to enter the correct code
    for attempt in range(3):
        if attempt > 0:
            print(f"Invalid code. {3-attempt} attempts remaining.")
            
        admin_code = input("Enter admin code (or type 'cancel' to return): ")
        
        if admin_code.lower() == 'cancel':
            print("Admin login cancelled.")
            return False
            
        # Use bcrypt to check the password
        if bcrypt.checkpw(admin_code.encode(), ADMIN_HASH):
            print("Admin login successful.")
            return True
    
    # If we get here, all attempts were used
    print("Too many failed attempts. Access denied.")
    return False



# Function to display all records for admin view
def display_all_records():
    try:
        with conn:
            cur = conn.cursor()
            
            # Get list of all tables
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cur.fetchall()
            
            print("\nAdmin View - Database Records")
            print("=" * 50)
            
            for table in tables:
                table_name = table[0]
                print(f"\nRecords in {table_name}:")
                print("-" * 50)
                
                # Get column names for the table
                cur.execute(f"PRAGMA table_info({table_name});")
                columns = cur.fetchall()
                column_names = [col[1] for col in columns]
                
                # Print column headers
                header = " | ".join(column_names)
                print(header)
                print("-" * len(header))
                
                # Get and print all rows from the table
                try:
                    cur.execute(f"SELECT * FROM {table_name} LIMIT 100;")
                    rows = cur.fetchall()
                    
                    if not rows:
                        print("(No records)")
                    else:
                        for row in rows:
                            # Format each value in the row for display
                            formatted_row = []
                            for value in row:
                                if value is None:
                                    formatted_row.append("NULL")
                                else:
                                    formatted_row.append(str(value))
                            
                            print(" | ".join(formatted_row))
                except sqlite3.Error as e:
                    print(f"Error retrieving records from {table_name}: {e}")
            
            # Options for admin
            print("\nAdmin Options:")
            print("1. View a specific table in detail")
            print("2. Return to main menu")
            
            option = input("Enter option (1-2): ")
            if option == '1':
                table_name = input("Enter table name to view: ")
                # Check if table exists
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?;", (table_name,))
                if cur.fetchone():
                    cur.execute(f"SELECT * FROM {table_name};")
                    rows = cur.fetchall()
                    
                    # Get column names
                    cur.execute(f"PRAGMA table_info({table_name});")
                    columns = cur.fetchall()
                    column_names = [col[1] for col in columns]
                    
                    # Print detailed view
                    print(f"\nDetailed view of {table_name}:")
                    print("-" * 50)
                    
                    if not rows:
                        print("(No records)")
                    else:
                        for row in rows:
                            print("-" * 30)
                            for i, col_name in enumerate(column_names):
                                print(f"{col_name}: {row[i]}")
                else:
                    handle_input_error(f"Table '{table_name}' does not exist")
            
    except sqlite3.Error as e:
        handle_critical_error(f"Database error while displaying records: {e}")


def member_menu(member_id):
    while True:
        print("\nLibrary System Menu:")
        print("1. Find an item")
        print("2. Borrow an item")
        print("3. Return an item")
        print("4. Donate an item")
        print("5. Find an event")
        print("6. Register for an event")
        print("7. Volunteer for an event")
        print("8. Ask for help from a librarian")
        print("9. View your fines")
        print("10. Pay fines")
        print("11. Cancel event registration")
        print("12. Exit to Main Menu")
        
        choice = input("Enter your choice (1-12): ")
        
        if choice == '1':
            title = input("Enter the title to search: ")
            find_item(title)
        
        elif choice == '2':
            item_id = safe_int_input("Enter the Item ID to borrow: ")
            if item_id is not None:
                borrow_item(member_id, item_id)
        
        elif choice == '3':
            borrowing_id = safe_int_input("Enter the Borrowing ID to return: ")
            if borrowing_id is not None:
                return_item(borrowing_id)
        elif choice == '4':
            title = input("Enter the title of the item to donate: ")
            if not title.strip():
                handle_input_error("Title cannot be empty")
                continue
                
            print("\nValid item types: Print Book, Online Book, Magazine, Journal, CD, Record")
            type = input("Enter the type: ")
            
            reference_only_input = input("Is this item reference-only (not borrowable)? (yes/no): ").lower()
            reference_only = reference_only_input == 'yes'
            
            donate_item(member_id, title, type, reference_only=reference_only)
        
        elif choice == '5':
            event_name = input("Enter the event name to search: ")
            find_event(event_name)
        
        elif choice == '6':
            event_id = safe_int_input("Enter the Event ID to register: ")
            if event_id is not None:
                register_event(member_id, event_id)
        
        elif choice == '7':
            event_id = safe_int_input("Enter the Event ID to volunteer for: ")
            if event_id is not None:
                role = input("Enter your volunteer role (e.g., 'Usher'): ")
                volunteer_event(member_id, event_id, role)
        
        elif choice == '8':
            question = input("Enter your question for the librarian: ")
            ask_librarian(member_id, question)

        elif choice == '9':
            with conn:
                cur = conn.cursor()
                cur.execute("SELECT TotalFine FROM Fine WHERE MemberID = ?", (member_id,))
                fine = cur.fetchone()
                if fine and fine[0] > 0:
                    print(f"\nYour total fine is: ${fine[0]:.2f}")
                    print("Please visit the library front desk to pay your fine.")
                    print("You cannot borrow additional items until your fine is paid.")
                    
                    # Optional: Show the items that incurred fines
                    cur.execute("""
                        SELECT b.BorrowingID, i.Title, b.DueDate, b.ReturnDate, b.FineAmount 
                        FROM Borrowing b
                        JOIN Item i ON b.ItemID = i.ItemID
                        WHERE b.MemberID = ? AND b.FineAmount > 0
                        ORDER BY b.ReturnDate DESC
                    """, (member_id,))
                    fine_items = cur.fetchall()
                    
                    if fine_items:
                        print("\nItems with fines:")
                        for item in fine_items:
                            print(f"Borrowing ID: {item[0]}, Title: {item[1]}")
                            print(f"Due: {item[2]}, Returned: {item[3]}, Fine: ${item[4]:.2f}")
                            print("-" * 40)
                else:
                    print("\nYou have no outstanding fines.")
        
        elif choice == '10':
            pay_fine(member_id)
        
        elif choice == '11':
            # First, show the user which events they're registered for
            with conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT e.EventID, e.Name, e.Date, e.Time 
                    FROM Event e
                    JOIN Event_Member em ON e.EventID = em.EventID
                    WHERE em.MemberID = ?
                    ORDER BY e.Date
                """, (member_id,))
                registered_events = cur.fetchall()
                
                if not registered_events:
                    print("\nYou are not registered for any events.")
                    continue
                    
                print("\nYour Registered Events:")
                for event in registered_events:
                    print(f"ID: {event[0]}, {event[1]} on {event[2]} at {event[3]}")
            
            event_id = safe_int_input("\nEnter the Event ID to cancel registration: ")
            if event_id is not None:
                cancel_event_registration(member_id, event_id)
        
        elif choice == '12':
            print("Returning to the main menu...")
            break
        
        
        
        else:
            handle_input_error("Invalid choice (must be 1-11)")
        
# Run the application
if __name__ == "__main__":
    try:
        main()
    finally:
        if conn:
            conn.close()
            print("Closed database successfully")