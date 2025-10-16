import os
import json
import requests
import time # Import time for use in exponential backoff
from flask import Flask, request, jsonify, render_template_string, redirect, url_for

# --- 1. FLASK APPLICATION SETUP ---
app = Flask(__name__)

# Simple in-memory storage for tasks and expenses (simulates a database)
# Structure: [{'task_id': 'uuid', 'text': '...', 'location': '...'}]
tasks = []
task_id_counter = 1

# Structure: [{'expense_id': 'uuid', 'description': '...', 'amount': '0.00', 'category': '...'}]
expenses = []
expense_id_counter = 1

# Budget tracking variable (initial value)
total_trip_budget = 0.00

# --- 2. GEMINI API CONFIGURATION ---
# IMPORTANT: Set your API key as an environment variable for security
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent"

# --- 3. BACKEND ROUTE: LOCATION SUGGESTIONS (Gemini API Call) ---

@app.route('/get_suggestions', methods=['POST'])
def get_suggestions():
    """
    Handles the request for location suggestions by calling the Gemini API
    with Google Search grounding and structured output, including coordinates.
    """
    data = request.json
    query = data.get('query', '').strip()

    if len(query) < 3:
        # Prevent API call for very short, non-specific queries
        return jsonify([])

    # System instruction defining the model's role and structured output requirement
    system_prompt = (
        "You are a specialized location search engine. Based on the user's query, use the Google Search Tool "
        "to find relevant businesses, landmarks, or addresses. For each location, return the name, full address, "
        "and its precise latitude and longitude as a number type. Return the results as a JSON array of objects. "
        "Only return the JSON, no commentary, markdown, or text outside the JSON block. Prioritize accuracy and popular locations."
    )

    # Define the JSON schema for the output (Updated to include coordinates)
    response_schema = {
        "type": "ARRAY",
        "description": "A list of suggested locations.",
        "items": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "description": "The name of the location or business."},
                "address": {"type": "STRING", "description": "The full address of the location."},
                "latitude": {"type": "NUMBER", "description": "The latitude of the location."},
                "longitude": {"type": "NUMBER", "description": "The longitude of the location."}
            },
            "required": ["name", "address", "latitude", "longitude"]
        }
    }

    payload = {
        "contents": [{"parts": [{"text": f"Find up to 5 locations for \"{query}\""}]}],
        "tools": [{"google_search": {} }],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema
        },
    }

    headers = {'Content-Type': 'application/json'}
    params = {'key': GEMINI_API_KEY} 

    try:
        # Retry logic for robust API calling (Exponential Backoff)
        max_retries = 3
        delay = 1.0
        
        for i in range(max_retries):
            response = requests.post(GEMINI_API_URL, headers=headers, params=params, data=json.dumps(payload))
            
            if response.status_code == 200:
                result = response.json()
                # Safely extract the JSON string text from the candidate structure
                json_text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
                
                # Attempt to parse the JSON output from the model
                try:
                    suggestions = json.loads(json_text)
                    return jsonify(suggestions)
                except json.JSONDecodeError:
                    print(f"Error parsing model JSON output: {json_text[:200]}...")
                    # Return an empty list for robust failure in the UI
                    return jsonify([]) 
            
            # Handle rate limiting (429) or temporary server issues (500, 503)
            if response.status_code in [429, 500, 503] and i < max_retries - 1:
                time.sleep(delay)
                delay *= 2 # Exponential increase
            else:
                print(f"API Error (Status {response.status_code}): {response.text}")
                # For non-recoverable errors (e.g., 400, 403), return an empty list to prevent UI crash
                return jsonify([]) 
                
        # If all retries fail
        return jsonify([])

    except Exception as e:
        print(f"Unexpected error during API call: {e}")
        return jsonify([])

# --- 4. BACKEND ROUTES: TO-DO LIST & BUDGET CRUD (Simulated) ---

@app.route('/', methods=['GET'])
def index():
    """Renders the main Management Dashboard page."""
    global total_trip_budget
    
    # Calculate total expenses for display
    total_expenses = sum(float(e.get('amount', '0.00')) for e in expenses)
    
    # Calculate remaining budget
    remaining_budget = total_trip_budget - total_expenses
    
    # Pass all variables to the HTML template
    return render_template_string(
        HTML_TEMPLATE, 
        tasks=tasks, 
        expenses=expenses, 
        total_expenses=total_expenses,
        total_trip_budget=total_trip_budget,
        remaining_budget=remaining_budget
    )

@app.route('/set_budget', methods=['POST'])
def set_budget():
    """Handles setting the total trip budget."""
    global total_trip_budget
    
    budget_str = request.form.get('total-budget-input', '0.00').strip()
    
    try:
        new_budget = float(budget_str)
        # Ensure budget is non-negative
        if new_budget >= 0:
            total_trip_budget = float(f"{new_budget:.2f}") # Store as float rounded to 2 decimals
    except ValueError:
        # Ignore invalid input
        pass
    
    return redirect(url_for('index'))


@app.route('/add_task', methods=['POST'])
def add_task():
    """Handles adding a new task to the list."""
    global task_id_counter
    
    # Extract data from the form submission
    task_text = request.form.get('task-input', '').strip()
    location_text = request.form.get('location-input', '').strip()

    if task_text:
        new_task = {
            'task_id': str(task_id_counter),
            'text': task_text,
            'location': location_text,
        }
        tasks.insert(0, new_task) # Add to the top
        task_id_counter += 1
    
    # Redirect back to the home page to display the updated list
    return redirect(url_for('index'))

@app.route('/delete_task/<task_id>', methods=['POST'])
def delete_task(task_id):
    """Handles deleting a task by ID."""
    global tasks
    # Filter the list, keeping only tasks whose ID does not match
    tasks = [task for task in tasks if task.get('task_id') != task_id]
    
    return redirect(url_for('index'))

# --- BACKEND ROUTES: EXPENSE MANAGEMENT (Simulated) ---

@app.route('/add_expense', methods=['POST'])
def add_expense():
    """Handles adding a new expense, allowing 0.00 amount for 'free' items."""
    global expense_id_counter
    
    description = request.form.get('expense-description', '').strip()
    amount_str = request.form.get('expense-amount', '').strip()
    category = request.form.get('expense-category', 'Other').strip()

    try:
        amount_float = float(amount_str)
    except ValueError:
        # If amount is invalid, return without adding
        return redirect(url_for('index'))

    # Allow amount_float >= 0 to include 'free' expenses.
    if description and amount_float >= 0:
        new_expense = {
            'expense_id': str(expense_id_counter),
            'description': description,
            'amount': f"{amount_float:.2f}", # Store as formatted string
            'category': category,
        }
        expenses.insert(0, new_expense) # Add to the top
        expense_id_counter += 1
    
    return redirect(url_for('index'))

@app.route('/delete_expense/<expense_id>', methods=['POST'])
def delete_expense(expense_id):
    """Handles deleting an expense by ID."""
    global expenses
    # Filter the list, keeping only expenses whose ID does not match
    expenses = [e for e in expenses if e.get('expense_id') != expense_id]
    
    return redirect(url_for('index'))


# --- 5. HTML TEMPLATE (JINJA2 EMBEDDED) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trip & Task Management Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
        body {
            font-family: 'Inter', sans-serif;
            background-color: #f3f4f6;
        }
        /* Style for suggestions container to sit above other content */
        .suggestions-container-wrapper {
            position: relative;
        }
        /* Hide the custom modal by default */
        .custom-modal {
            display: none;
        }
        /* Map image styling */
        #location-map-img {
            width: 100%;
            height: 256px; /* Fixed height for map */
            object-fit: cover; /* Ensure image covers the area */
            border-radius: 0.5rem;
        }
        /* Utility class to hide the map preview */
        .hidden {
            display: none;
        }
        /* Card styling for summary */
        .summary-card-base {
            padding: 1.5rem;
            border-radius: 0.75rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1);
            transition: all 0.3s ease;
        }
    </style>
</head>
<body class="min-h-screen p-4 sm:p-8 bg-gray-100">

    <div class="max-w-6xl mx-auto" id="app-container">
        <header class="text-center mb-10">
             <h1 class="text-4xl font-extrabold text-gray-900 tracking-tight">Trip & Task Management Dashboard</h1>
             <p class="text-gray-600 mt-2">To-Do List with Location Search & Real-time Budget Tracker</p>
             <p class="text-sm text-indigo-500 mt-2 font-semibold">Developed by Harsh03</p>
        </header>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-10">
            
            <!-- ========== LEFT COLUMN: TO-DO MANAGEMENT (Task & Location) ========== -->
            <div>
                <h2 class="text-3xl font-bold text-indigo-700 mb-6 pb-2 border-b-2 border-indigo-200">To-Do List</h2>
                
                <!-- Task Input Form -->
                <div class="bg-white p-6 rounded-xl shadow-2xl mb-8">
                    <form id="task-form" action="{{ url_for('add_task') }}" method="POST">
                        <div class="mb-4">
                            <label for="task-input" class="block text-sm font-medium text-gray-700 mb-1">Task Description</label>
                            <input type="text" name="task-input" id="task-input" placeholder="e.g., Pick up dry cleaning" required
                                    class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-indigo-500 focus:border-indigo-500 transition duration-150 shadow-sm">
                        </div>

                        <div class="mb-4 suggestions-container-wrapper">
                            <label for="location-input" class="block text-sm font-medium text-gray-700 mb-1">Location (Search & select exact place)</label>
                            <div class="flex space-x-2">
                                <input type="text" name="location-input" id="location-input" placeholder="e.g., The best Italian restaurant"
                                        class="flex-grow px-4 py-3 border border-gray-300 rounded-lg focus:ring-indigo-500 focus:border-indigo-500 transition duration-150 shadow-sm">
                            </div>
                            
                            <!-- Location Suggestions Dropdown -->
                            <div id="suggestions-container" class="absolute z-20 w-full mt-1 max-h-60 overflow-y-auto bg-white border border-gray-200 rounded-lg shadow-xl">
                                <!-- Suggestions will be injected here -->
                            </div>
                        </div>

                        <!-- Map Preview Area (Uses Google Static Maps Placeholder) -->
                        <div id="map-preview-area" class="mt-4 bg-indigo-50 p-4 rounded-xl border border-indigo-200 hidden z-10">
                            <h4 class="font-bold text-indigo-700 mb-3 flex justify-between items-center">
                                Confirm Location (Google Maps Preview)
                                <button type="button" id="select-location-btn" class="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition duration-150 shadow-md transform hover:scale-105">
                                    Select This Location
                                </button>
                            </h4>
                            <!-- Image tag to hold the Google Static Map placeholder -->
                            <img id="location-map-img" alt="Google Map Preview" class="w-full h-64 rounded-lg shadow-inner border border-gray-300 bg-gray-200" 
                                 src="https://placehold.co/400x256/E0E7FF/4338CA?text=Search+a+Location+for+Map+Preview">
                            <p id="map-address-display" class="mt-2 text-sm text-indigo-800 font-medium truncate"></p>
                        </div>

                        <button type="submit"
                                class="w-full bg-indigo-600 text-white font-semibold py-3 rounded-lg hover:bg-indigo-700 transition duration-200 transform hover:scale-[1.01] shadow-lg mt-4">
                            Add Task
                        </button>
                    </form>
                </div>

                <!-- To-Do List -->
                <h3 class="text-xl font-bold text-gray-700 mb-3">Tasks to Complete</h3>
                <ul id="todo-list" class="space-y-3">
                    {% if tasks %}
                        {% for task in tasks %}
                            <li class="flex justify-between items-center bg-white p-4 my-2 rounded-lg shadow-md border-l-4 border-indigo-500">
                                <div class="flex flex-col">
                                    <span class="text-gray-900 font-semibold text-lg">{{ task.text }}</span>
                                    {% if task.location %}
                                        <span class="text-sm text-indigo-600 flex items-center mt-1">
                                            <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.828 0l-4.243-4.243a8 8 0 1111.314 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                                            {{ task.location }}
                                        </span>
                                    {% else %}
                                        <span class="text-sm text-gray-400">No location set</span>
                                    {% endif %}
                                </div>
                                <form action="{{ url_for('delete_task', task_id=task.task_id) }}" method="POST" class="delete-form" data-type="task">
                                    <button type="submit"
                                            class="ml-4 p-2 bg-red-500 text-white rounded-full hover:bg-red-600 transition duration-200 transform hover:scale-105 shadow-md">
                                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                    </button>
                                </form>
                            </li>
                        {% endfor %}
                    {% else %}
                        <li class="p-4 my-2 bg-white rounded-lg shadow-md text-center text-gray-500">No tasks yet. Add one above!</li>
                    {% endif %}
                </ul>
            </div>

            <!-- ========== RIGHT COLUMN: BUDGET & EXPENSE MANAGEMENT ========== -->
            <div>
                <h2 class="text-3xl font-bold text-green-700 mb-6 pb-2 border-b-2 border-green-200">Budget & Expense Tracking</h2>

                <!-- Budget Summary Card -->
                <div class="grid grid-cols-3 gap-4 mb-8">
                    <!-- Total Budget -->
                    <div class="summary-card-base bg-blue-50 border-t-4 border-blue-500">
                        <p class="text-sm font-medium text-gray-600">Total Budget</p>
                        <p class="text-2xl font-extrabold text-blue-700 mt-1">₹{{ '%.2f' | format(total_trip_budget) }}</p>
                    </div>
                    <!-- Total Spent -->
                    <div class="summary-card-base bg-red-50 border-t-4 border-red-500">
                        <p class="text-sm font-medium text-gray-600">Total Spent</p>
                        <p class="text-2xl font-extrabold text-red-700 mt-1">₹{{ '%.2f' | format(total_expenses) }}</p>
                    </div>
                    <!-- Remaining Budget -->
                    <div class="summary-card-base bg-green-50 border-t-4 {% if remaining_budget >= 0 %}border-green-500{% else %}border-orange-500{% endif %}">
                        <p class="text-sm font-medium text-gray-600">Remaining Budget</p>
                        <p class="text-2xl font-extrabold {% if remaining_budget >= 0 %}text-green-700{% else %}text-orange-700{% endif %} mt-1">
                            ₹{{ '%.2f' | format(remaining_budget) }}
                        </p>
                    </div>
                </div>

                <!-- Conditional Budget Setter/Editor -->
                {% if total_trip_budget == 0.00 %}
                <!-- Initial Budget Setter (Only shows once) -->
                <div id="initial-budget-setter" class="bg-white p-6 rounded-xl shadow-2xl mb-8 border-2 border-blue-500">
                    <h3 class="text-xl font-bold text-blue-700 mb-3">Set Initial Trip Budget (One-time)</h3>
                    <form action="{{ url_for('set_budget') }}" method="POST" class="flex space-x-3">
                        <input type="number" step="0.01" min="0.00" name="total-budget-input" id="total-budget-input" placeholder="e.g., 2500.00" 
                                required
                                class="flex-grow px-4 py-3 border border-gray-300 rounded-lg focus:ring-blue-500 focus:border-blue-500 transition duration-150 shadow-sm">
                        <button type="submit"
                                class="bg-blue-600 text-white font-semibold py-3 px-6 rounded-lg hover:bg-blue-700 transition duration-200 transform hover:scale-[1.01] shadow-md">
                            Set Budget
                        </button>
                    </form>
                </div>
                {% else %}
                <!-- Budget Editor (Shows after budget is set) -->
                <div class="bg-white p-6 rounded-xl shadow-2xl mb-8 border-2 border-blue-100">
                    <div class="flex justify-between items-center">
                        <h3 class="text-xl font-bold text-blue-700">Trip Budget Set</h3>
                        <button type="button" id="edit-budget-btn" class="px-3 py-1 text-sm bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition duration-150">
                            Edit Budget
                        </button>
                    </div>
                    <div id="edit-budget-form-container" class="mt-4 hidden">
                        <form action="{{ url_for('set_budget') }}" method="POST" class="flex space-x-3 mt-3">
                            <input type="number" step="0.01" min="0.00" name="total-budget-input" id="total-budget-input" placeholder="e.g., 2500.00" 
                                    value="{{ '%.2f' | format(total_trip_budget) }}" required
                                    class="flex-grow px-4 py-3 border border-gray-300 rounded-lg focus:ring-blue-500 focus:border-blue-500 transition duration-150 shadow-sm">
                            <button type="submit"
                                    class="bg-blue-600 text-white font-semibold py-3 px-6 rounded-lg hover:bg-blue-700 transition duration-200 transform hover:scale-[1.01] shadow-md">
                                Update
                            </button>
                        </form>
                    </div>
                </div>
                {% endif %}


                <!-- Expense Input Form -->
                <div class="bg-white p-6 rounded-xl shadow-2xl mb-8 border-2 border-green-100">
                    <h3 class="text-xl font-bold text-green-700 mb-4">Add New Expense</h3>
                    <form id="expense-form" action="{{ url_for('add_expense') }}" method="POST">
                        <div class="mb-4">
                            <label for="expense-description" class="block text-sm font-medium text-gray-700 mb-1">Description</label>
                            <input type="text" name="expense-description" id="expense-description" placeholder="e.g., Coffee, groceries" required
                                    class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-green-500 focus:border-green-500 transition duration-150 shadow-sm">
                        </div>

                        <div class="grid grid-cols-2 gap-4 mb-4">
                            <div>
                                <label for="expense-amount" class="block text-sm font-medium text-gray-700 mb-1">Amount (₹)</label>
                                <input type="number" step="0.01" min="0.00" name="expense-amount" id="expense-amount" placeholder="e.g., 5.50 or 0.00 for free" required
                                        class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-green-500 focus:border-green-500 transition duration-150 shadow-sm">
                            </div>
                            <div>
                                <label for="expense-category" class="block text-sm font-medium text-gray-700 mb-1">Category</label>
                                <select name="expense-category" id="expense-category"
                                        class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-green-500 focus:border-green-500 transition duration-150 shadow-sm bg-white">
                                    <option value="Food">Food</option>
                                    <option value="Shopping">Shopping</option>
                                    <option value="Utilities">Utilities</option>
                                    <option value="Transport">Transport</option>
                                    <option value="Other">Other</option>
                                </select>
                            </div>
                        </div>

                        <button type="submit"
                                class="w-full bg-green-600 text-white font-semibold py-3 rounded-lg hover:bg-green-700 transition duration-200 transform hover:scale-[1.01] shadow-lg">
                            Add Expense
                        </button>
                    </form>
                </div>


                <!-- Expense List Display -->
                <h3 class="text-xl font-bold text-gray-700 mb-3">Recent Expenses</h3>
                <ul id="expense-list" class="space-y-3">
                    {% if expenses %}
                        {% for expense in expenses %}
                            <li class="flex justify-between items-center bg-white p-4 my-2 rounded-lg shadow-md border-l-4 border-green-500">
                                <div class="flex flex-col">
                                    <span class="text-gray-900 font-semibold text-lg">{{ expense.description }}</span>
                                    <span class="text-sm text-gray-500">{{ expense.category }}</span>
                                </div>
                                <div class="flex items-center space-x-4">
                                    <span class="text-lg font-bold text-green-600">${{ expense.amount }}</span>
                                    <form action="{{ url_for('delete_expense', expense_id=expense.expense_id) }}" method="POST" class="delete-form" data-type="expense">
                                        <button type="submit"
                                                class="p-2 bg-red-500 text-white rounded-full hover:bg-red-600 transition duration-200 transform hover:scale-105 shadow-md">
                                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                        </button>
                                    </form>
                                </div>
                            </li>
                        {% endfor %}
                    {% else %}
                        <li class="p-4 my-2 bg-white rounded-lg shadow-md text-center text-gray-500">No expenses recorded yet.</li>
                    {% endif %}
                </ul>
            </div>
        </div>
    </div>

    <!-- Custom Modal Structure (Hidden) -->
    <div id="confirmation-modal" class="custom-modal fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" aria-modal="true" role="dialog">
        <div class="bg-white p-6 rounded-lg shadow-2xl max-w-sm mx-4 text-center">
            <p class="text-lg font-semibold mb-4">Confirm Deletion</p>
            <p id="modal-text" class="mb-6">Are you sure you want to delete this item?</p>
            <div class="flex justify-center space-x-4">
                <button id="cancel-delete" class="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300">Cancel</button>
                <button id="confirm-delete" class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700">Delete</button>
            </div>
        </div>
    </div>

    <!-- Javascript for Real-time Location Suggestions via AJAX and Delete Confirmation -->
    <script>
        // Global Variables
        let selectedLocationData = null; // Stores data of the currently selected suggestion

        // --- Confirmation Modal Logic ---
        document.addEventListener('DOMContentLoaded', () => {
            const modal = document.getElementById('confirmation-modal');
            const confirmBtn = document.getElementById('confirm-delete');
            const cancelBtn = document.getElementById('cancel-delete');
            let formToSubmit = null;

            document.querySelectorAll('.delete-form').forEach(form => {
                form.addEventListener('submit', function(e) {
                    e.preventDefault(); // Stop the default submission
                    formToSubmit = this;
                    const type = formToSubmit.getAttribute('data-type');
                    document.getElementById('modal-text').textContent = `Are you sure you want to delete this ${type}?`;
                    modal.style.display = 'flex'; // Show modal
                });
            });

            confirmBtn.addEventListener('click', () => {
                if (formToSubmit) {
                    // Re-submit the form without preventing default action
                    formToSubmit.submit();
                    formToSubmit = null;
                }
                modal.style.display = 'none'; // Hide modal
            });

            cancelBtn.addEventListener('click', () => {
                formToSubmit = null;
                modal.style.display = 'none'; // Hide modal
            });
            
            // --- Budget Edit Logic (NEW) ---
            const editBudgetBtn = document.getElementById('edit-budget-btn');
            const editBudgetFormContainer = document.getElementById('edit-budget-form-container');

            if (editBudgetBtn && editBudgetFormContainer) {
                editBudgetBtn.addEventListener('click', () => {
                    editBudgetFormContainer.classList.toggle('hidden');
                    editBudgetBtn.textContent = editBudgetFormContainer.classList.contains('hidden') ? 'Edit Budget' : 'Hide Form';
                });
            }
        });

        // --- Location Map and Suggestion Logic ---
        const locationInput = document.getElementById('location-input');
        const suggestionsContainer = document.getElementById('suggestions-container');
        const mapPreviewArea = document.getElementById('map-preview-area');
        const selectLocationBtn = document.getElementById('select-location-btn');
        const locationMapImg = document.getElementById('location-map-img');
        const mapAddressDisplay = document.getElementById('map-address-display');
        let debounceTimer;

        // Initializes Google Static Map Image (Simulated/Placeholder)
        function updateMapPreview(lat, lng, name, address) {
            // Using a placehold.co URL to visually confirm the coordinates
            // This URL shows the lat/lng and name, simulating a map marker at the center.
            const mapPlaceholderUrl = `https://placehold.co/400x256/4338CA/ffffff?text=Google+Map+Preview:%0A${lat.toFixed(4)},${lng.toFixed(4)}%0A${name}`;
            
            locationMapImg.src = mapPlaceholderUrl;
            locationMapImg.alt = `Google Map Preview for ${name}`;
            mapAddressDisplay.textContent = `Location: ${address}`;

            mapPreviewArea.classList.remove('hidden');
        }

        // Fetches suggestions from the Flask backend
        async function fetchSuggestions(query) {
            suggestionsContainer.innerHTML = `
                <div class="p-3 text-sm text-indigo-500 flex items-center">
                    <svg class="animate-spin -ml-1 mr-3 h-5 w-5 text-indigo-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Searching Google Maps...
                </div>`;
            suggestionsContainer.classList.add('border');
            
            try {
                const response = await fetch('/get_suggestions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: query })
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const suggestions = await response.json();
                renderSuggestions(suggestions);
            } catch (error) {
                console.error("Error fetching suggestions:", error);
                renderSuggestions([], true); // Pass error flag
            }
        }

        // Renders suggestions in the dropdown
        function renderSuggestions(suggestions, isError = false) {
            suggestionsContainer.innerHTML = ''; // Clear previous suggestions
            
            if (isError) {
                 suggestionsContainer.innerHTML = `
                      <div class="p-3 text-sm text-red-500">Failed to load Google Maps suggestions.</div>
                  `;
                 suggestionsContainer.classList.add('border');
                 return;
            }
            
            if (suggestions.length === 0) {
                 suggestionsContainer.innerHTML = `
                      <div class="p-3 text-sm text-gray-500">No locations found.</div>
                  `;
                 suggestionsContainer.classList.remove('border');
                 return;
            }
            
            suggestionsContainer.classList.add('border');

            suggestions.forEach(suggestion => {
                const isValid = typeof suggestion.latitude === 'number' && typeof suggestion.longitude === 'number';

                const item = document.createElement('div');
                item.className = 'p-3 cursor-pointer hover:bg-indigo-50 border-b border-gray-100';
                item.innerHTML = `
                    <p class="font-medium text-gray-800">${suggestion.name}</p>
                    <p class="text-sm text-gray-500">${suggestion.address}</p>
                    ${!isValid ? '<p class="text-xs text-red-400">Map data unavailable.</p>' : ''}
                `;
                
                // Add click listener to select the location only if valid
                if (isValid) {
                    item.addEventListener('click', () => selectSuggestion(suggestion));
                } else {
                    item.classList.add('opacity-60', 'cursor-not-allowed');
                }
                
                suggestionsContainer.appendChild(item);
            });
        }

        // Handler when a suggestion is clicked
        function selectSuggestion(suggestion) {
            selectedLocationData = suggestion;
            
            // Hide suggestions
            suggestionsContainer.innerHTML = '';
            suggestionsContainer.classList.remove('border');
            
            // Update input visually with the full name and address for clarity
            locationInput.value = `${suggestion.name}, ${suggestion.address}`;

            // Update the map preview (Now using the new function for the image)
            updateMapPreview(suggestion.latitude, suggestion.longitude, suggestion.name, suggestion.address);
        }

        // Handler for the "Select Location" button click
        selectLocationBtn.addEventListener('click', (e) => {
            e.preventDefault(); // Prevent form submission
            
            if (selectedLocationData) {
                // Finalize the location text in the input field
                locationInput.value = `${selectedLocationData.name}, ${selectedLocationData.address}`;
            }

            // Hide the map preview area after selection
            mapPreviewArea.classList.add('hidden');
        });

        // Event listener for typing in the location input
        locationInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            
            // Clear previous debounce timer
            clearTimeout(debounceTimer);

            // Reset selected location data and hide map/suggestions if input is cleared
            if (query.length === 0) {
                selectedLocationData = null;
                suggestionsContainer.innerHTML = '';
                suggestionsContainer.classList.remove('border');
                mapPreviewArea.classList.add('hidden');
                return;
            }
            
            // Set a new debounce timer to fetch suggestions after 300ms
            if (query.length >= 3) {
                debounceTimer = setTimeout(() => {
                    fetchSuggestions(query);
                }, 300);
            } else {
                // Clear suggestions if query is too short but not empty
                suggestionsContainer.innerHTML = '';
                suggestionsContainer.classList.remove('border');
            }
        });

        // Hide suggestions when clicking outside the container or input
        document.addEventListener('click', function(e) {
            const isClickInsideInput = locationInput.contains(e.target);
            const isClickInsideSuggestions = suggestionsContainer.contains(e.target);
            
            if (!isClickInsideInput && !isClickInsideSuggestions) {
                // If the map preview is visible, don't clear the input value, just hide suggestions
                if(mapPreviewArea.classList.contains('hidden')) {
                     suggestionsContainer.innerHTML = '';
                     suggestionsContainer.classList.remove('border');
                }
            }
        });
    </script>
        <footer class="text-center mt-10 py-4 text-sm text-gray-600 border-t border-gray-300">
        © <span id="year"></span> @Harsh03 — All rights received | Developed by <strong>Harsh03</strong>
    </footer>
</body>
</html>
"""

# --- 6. RUN THE FLASK APP ---
if __name__ == '__main__':
    # Flask startup command, essential for running the app
    app.run(debug=True)
