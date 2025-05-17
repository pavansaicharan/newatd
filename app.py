from flask import Flask, render_template, request, session, redirect, url_for
from playwright.sync_api import sync_playwright
import time
import requests
import os

app = Flask(__name__)
# Use environment variable for secret key in production
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key_here')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True

# College portal URLs
COLLEGE_LOGIN_URL = "http://43.250.40.63/Login.aspx?ReturnUrl=%2fStudentLogin%2fMainStud.aspx"
COLLEGE_DASHBOARD_URL = "http://43.250.40.63/StudentLogin/MainStud.aspx"

def is_college_portal_available():
    """Check if the college portal is accessible"""
    try:
        response = requests.get(COLLEGE_LOGIN_URL, timeout=10)
        return response.status_code == 200
    except:
        return False

@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            
            if not is_college_portal_available():
                return render_template('login.html', error="College portal is currently unavailable. Please try again later.")
            
            # Store credentials in session
            session['college_credentials'] = {
                'username': username,
                'password': password
            }
            
            try:
                # Scrape attendance data
                attendance_data = scrape_attendance(username, password)
                
                # Store scraped data in session
                session['scraped_data'] = {
                    'current_attended': attendance_data['attended'],
                    'current_conducted': attendance_data['conducted']
                }
                
                return redirect(url_for('index'))
            except Exception as e:
                print(f"Login error: {str(e)}")  # Add logging
                return render_template('login.html', error=f"Failed to fetch attendance: {str(e)}")
        
        return render_template('login.html')
    except Exception as e:
        print(f"Unexpected error in login route: {str(e)}")  # Add logging
        return render_template('login.html', error="An unexpected error occurred. Please try again.")

def scrape_attendance(username, password):
    from playwright.sync_api import sync_playwright
    import re

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # Step 1: Navigate to login page
            print("Navigating to login page...")
            page.goto(COLLEGE_LOGIN_URL, timeout=30000)

            # Step 2: Fill username
            print("Filling username...")
            page.fill('input[name="txtUserName"]', username)
            page.click('input[type="submit"]')

            # Step 3: Fill password
            print("Filling password...")
            page.fill('input[name="txtPassword"]', password)
            page.click('input[type="submit"]')

            # Step 4: Wait for navigation
            print("Waiting for dashboard...")
            try:
                page.wait_for_url(lambda url: "StudentLogin" in url or "Dashboard" in url, timeout=30000)
            except:
                if "StudentLogin" not in page.url:
                    page.screenshot(path='login_error.png')
                    raise Exception("Failed to reach dashboard after login")

            # Step 5: Dashboard redirection
            print("Looking for dashboard link...")
            dashboard_clicked = False
            dashboard_texts = [
                "Student Dashboard", "Dashboard",
                "Click Here to go Student Dashboard",
                "Student Panel", "Attendance", "View Attendance"
            ]
            for text in dashboard_texts:
                try:
                    if page.query_selector(f'text="{text}"'):
                        page.click(f'text="{text}"')
                        print(f"Clicked dashboard link: {text}")
                        dashboard_clicked = True
                        break
                except:
                    continue

            if not dashboard_clicked:
                all_links = page.query_selector_all('a')
                for link in all_links:
                    try:
                        link_text = link.inner_text().strip().lower()
                        if any(k in link_text for k in ['dashboard', 'attendance', 'student']):
                            link.click()
                            print(f"Clicked alternative link: {link_text}")
                            dashboard_clicked = True
                            break
                    except:
                        continue

            if not dashboard_clicked:
                page.screenshot(path='dashboard_error.png')
                raise Exception("Could not find any dashboard link")

            # Step 6: Wait for attendance section
            print("Locating attendance data...")
            # Wait for page to fully load
            page.wait_for_load_state('networkidle', timeout=30000)

            # Get the entire page content
            page_text = page.inner_text('body')
            
            # Use regex to find the attendance numbers after "Total"
            match = re.search(r'Total\D*(\d+)\D*(\d+)', page_text)
            if not match:
                # Alternative pattern if the first one fails
                match = re.search(r'Classes\s*Held\D*(\d+).*Classes\s*Attended\D*(\d+)', page_text, re.DOTALL)
            
            if not match:
                page.screenshot(path='attendance_error.png')
                with open('page_content.txt', 'w', encoding='utf-8') as f:
                    f.write(page_text)
                raise Exception("Could not find attendance numbers in page content")

            # Extract the numbers
            conducted = int(match.group(1))
            attended = int(match.group(2))

            # Validate the numbers
            if attended > conducted:
                raise Exception(f"Invalid data: attended ({attended}) > conducted ({conducted})")
            if conducted == 0:
                raise Exception("No classes conducted")

            print(f"Successfully extracted - Classes Held: {conducted}, Classes Attended: {attended}")
            return {
                'attended': attended,
                'conducted': conducted
            }

        except Exception as e:
            print(f"Scraping error: {str(e)}")
            page.screenshot(path='scraping_error.png')
            raise Exception(f"Attendance scraping failed: {str(e)}")
        finally:
            browser.close()

@app.route('/', methods=['GET', 'POST'])
def index():
    # Default values
    default_values = {
        'current_attended': 0,
        'current_conducted': 0,
        'willing_to_attend': 0,
        'conducted_to_add': 0,
        'custom_percentage_attend': 75,
        'custom_percentage_miss': 75
    }

    # Check if scraped data exists in session
    if 'scraped_data' in session:
        default_values.update({
            'current_attended': session['scraped_data']['current_attended'],
            'current_conducted': session['scraped_data']['current_conducted']
        })

    # Check if previous values are in session
    if 'previous_values' in session:
        default_values.update(session['previous_values'])

    if request.method == 'POST':
        try:
            # Get form data
            current_attended = int(request.form['current_attended'])
            current_conducted = int(request.form['current_conducted'])
            willing_to_attend = int(request.form['willing_to_attend'])
            conducted_to_add = int(request.form['conducted_to_add'])
            custom_percentage_attend = int(request.form.get('custom_percentage_attend', 75))
            custom_percentage_miss = int(request.form.get('custom_percentage_miss', 75))

            # Store values in session
            session['previous_values'] = {
                'current_attended': current_attended,
                'current_conducted': current_conducted,
                'willing_to_attend': willing_to_attend,
                'conducted_to_add': conducted_to_add,
                'custom_percentage_attend': custom_percentage_attend,
                'custom_percentage_miss': custom_percentage_miss
            }

            # Calculate attendance
            total_attended = current_attended + willing_to_attend
            total_conducted = current_conducted + conducted_to_add

            if total_conducted == 0:
                return render_template('index.html', error="Total classes conducted cannot be zero", **default_values)

            current_percentage = (current_attended / current_conducted) * 100 if current_conducted > 0 else 0
            future_percentage = (total_attended / total_conducted) * 100

            return render_template('result.html',
                                current_attended=current_attended,
                                current_conducted=current_conducted,
                                willing_to_attend=willing_to_attend,
                                conducted_to_add=conducted_to_add,
                                current_percentage=current_percentage,
                                future_percentage=future_percentage,
                                custom_percentage_attend=custom_percentage_attend,
                                custom_percentage_miss=custom_percentage_miss)
        except Exception as e:
            return render_template('index.html', error=f"An error occurred: {str(e)}", **default_values)

    return render_template('index.html', **default_values)

@app.route('/health')
def health():
    return 'OK', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)