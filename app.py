import os
import mysql.connector
import numpy as np
import pickle
from flask import Flask, render_template, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'smartresale_secret_key_2026')

# Cloud MySQL Database Helper Function (Aiven Configuration)
# Cloud MySQL Database Helper Function (Aiven Configuration with SSL disabled for connection stability)
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "mysql-183e7433-lakshmanchitikina123-a18e.f.aivencloud.com"),
        user=os.getenv("DB_USER", "avnadmin"),
        password=os.getenv("DB_PASSWORD", "AVNS_nZ_JCEfem70FTj1L-Pq"),
        database=os.getenv("DB_NAME", "defaultdb"),
        port=int(os.getenv("DB_PORT", 18035)),
        ssl_disabled=True
    )

# Automatically initialize MySQL table on startup
def init_db():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                category VARCHAR(100),
                brand VARCHAR(100),
                condition_type VARCHAR(100),
                location VARCHAR(100),
                description TEXT,
                original_price DECIMAL(10,2),
                price DECIMAL(10,2) NOT NULL,
                age INT,
                image_url TEXT,
                seller_name VARCHAR(100),
                seller_contact VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Database Initialization Error: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Run database initialization
init_db()

# Load ML model (Tries both 'model.pkl' and 'olx_price_prediction_model.pkl')
model = None
for model_path in ['olx_price_prediction_model.pkl', 'model.pkl']:
    try:
        if os.path.exists(model_path):
            with open(model_path, 'rb') as f:
                model = pickle.load(f)
                print(f"Loaded ML model from {model_path}")
                break
    except Exception as e:
        print(f"Model loading warning ({model_path}): {e}")

# 1. Home Route
@app.route('/')
def home():
    return render_template('index.html')

# 2. Sell Route (Redirects to /analyze form)
@app.route('/sell')
def sell():
    return redirect(url_for('analyze'))

# 3. Marketplace Route
@app.route('/marketplace')
def marketplace():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    condition = request.args.get('condition', '').strip()
    location = request.args.get('location', '').strip()
    price_min = request.args.get('price_min', '')
    price_max = request.args.get('price_max', '')
    sort = request.args.get('sort', 'newest')

    query = "SELECT * FROM items WHERE 1=1"
    params = []

    if q:
        query += " AND (title LIKE %s OR description LIKE %s OR brand LIKE %s)"
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%'])

    if category and category != 'All Categories':
        query += " AND category = %s"
        params.append(category)

    if condition and condition != 'Any Condition':
        query += " AND condition_type = %s"
        params.append(condition)

    if location:
        query += " AND location LIKE %s"
        params.append(f'%{location}%')

    if price_min:
        try:
            query += " AND price >= %s"
            params.append(float(price_min))
        except ValueError:
            pass

    if price_max:
        try:
            query += " AND price <= %s"
            params.append(float(price_max))
        except ValueError:
            pass

    if sort == 'price_asc':
        query += " ORDER BY price ASC"
    elif sort == 'price_desc':
        query += " ORDER BY price DESC"
    else:
        query += " ORDER BY id DESC"

    products = []
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params)
        products = cursor.fetchall()
    except Exception as e:
        print(f"Database query error: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template(
        'marketplace.html',
        products=products,
        q=q,
        category=category,
        condition=condition,
        location=location,
        price_min=price_min,
        price_max=price_max,
        sort=sort
    )

# 4. Analyze Route (Calculates valuation & saves listings to MySQL database)
@app.route('/analyze', methods=['GET', 'POST'])
def analyze():
    if request.method == 'POST':
        category_name = request.form.get('categoryName', '') or request.form.get('category', '')
        location = request.form.get('location', '')
        brand = request.form.get('brand', '')
        condition = request.form.get('condition', '')
        description = request.form.get('description', '')
        image_url = request.form.get('image_url', '')
        seller_name = request.form.get('seller_name', '')
        seller_contact = request.form.get('seller_contact', '')
        
        # Ensure title is never empty for database insertion
        raw_title = request.form.get('title', '').strip()
        if not raw_title:
            title = f"{brand} {category_name}".strip() or "Pre-owned Item"
        else:
            title = raw_title

        try:
            original_price = float(request.form.get('original_price', 0))
        except ValueError:
            original_price = 0.0

        try:
            age = int(request.form.get('age', 0))
        except ValueError:
            age = 0

        condition_factors = {
            'New': 0.95,
            'Like New': 0.85,
            'Good': 0.75,
            'Fair': 0.60,
            'Used': 0.50,
            'Poor': 0.30
        }
        
        factor = condition_factors.get(condition, 0.70)
        years = age / 12.0
        age_retention = max(0.20, (0.88 ** years))
        
        predicted_price = round(original_price * factor * age_retention, 2)
        min_price = round(predicted_price * 0.90, 2)
        max_price = round(predicted_price * 1.10, 2)

        # Saves listing when clicking "Post to Marketplace" or submitting form
        if request.form.get('save_item') or request.form.get('action') == 'save':
            conn = None
            cursor = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO items (title, category, brand, condition_type, location, description, original_price, price, age, image_url, seller_name, seller_contact)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (title, category_name, brand, condition, location, description, original_price, predicted_price, age, image_url, seller_name, seller_contact))
                conn.commit()
                flash("Item listed on the marketplace successfully!", "success")
                return redirect(url_for('marketplace'))
            except Exception as e:
                print(f"Database insertion error: {e}")
                flash("Failed to list item. Please try again.", "danger")
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

        return render_template(
            'analyze.html',
            predicted_price=predicted_price,
            min_price=min_price,
            max_price=max_price,
            categoryName=category_name,
            location=location,
            brand=brand,
            condition=condition,
            title=title,
            description=description,
            original_price=original_price,
            age=age,
            image_url=image_url,
            seller_name=seller_name,
            seller_contact=seller_contact
        )

    return render_template('analyze.html')

# 5. Item Detail Route
@app.route('/item/<int:item_id>')
def item_detail(item_id):
    conn = None
    cursor = None
    item = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM items WHERE id = %s', (item_id,))
        item = cursor.fetchone()
    except Exception as e:
        print(f"Error fetching item detail: {e}")
        flash("Database error occurred while fetching item details.", "danger")
        return redirect(url_for('marketplace'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    
    if item is None:
        flash("Item not found!", "danger")
        return redirect(url_for('marketplace'))
        
    return render_template('item.html', product=item)

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
