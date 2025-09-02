from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import google.generativeai as genai
import mysql.connector
import json
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Configure Gemini API - UTILISE VARIABLE D'ENVIRONNEMENT
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY environment variable is required!")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# MySQL Configuration - TOUTES LES CONFIGS DEPUIS L'ENVIRONNEMENT
MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'database': os.getenv('MYSQL_DATABASE', 'recipe_app'),
    'charset': 'utf8mb4'
}

def get_db_connection():
    return mysql.connector.connect(**MYSQL_CONFIG)

def init_database():
    """Initialize database and create tables"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create recipes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recipes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                ingredients JSON NOT NULL,
                instructions JSON NOT NULL,
                prep_time VARCHAR(50),
                difficulty VARCHAR(20),
                source_ingredients TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Database initialized successfully")
        
    except mysql.connector.Error as e:
        print(f"❌ Database initialization error: {e}")
        return False
    return True

# NOUVEAU: Route pour servir le frontend
@app.route('/')
def index():
    """Serve the main HTML page"""
    return send_from_directory('.', 'index.html')

@app.route('/api/recipes', methods=['POST'])
def get_recipes():
    try:
        data = request.get_json()
        ingredients = data.get('ingredients', '')
        
        if not ingredients:
            return jsonify({'error': 'No ingredients provided'}), 400
        
        # Create prompt for Gemini
        prompt = f"""
        Create 3 simple recipes using these ingredients: {ingredients}
        
        Return ONLY a JSON array with this exact format:
        [
          {{
            "title": "Recipe Name",
            "ingredients": ["ingredient1", "ingredient2", "ingredient3"],
            "instructions": ["step1", "step2", "step3"],
            "prep_time": "15 mins",
            "difficulty": "Easy"
          }}
        ]
        
        Make sure recipes are practical and use common cooking methods.
        """
        
        # Get response from Gemini
        try:
            response = model.generate_content(prompt)
            print(f"✅ Gemini response received: {response.text[:100]}...")
        except Exception as gemini_error:
            print(f"❌ Gemini API Error: {gemini_error}")
            return jsonify({'error': f'AI service error: {str(gemini_error)}'}), 500
        
        # Parse the JSON response
        try:
            recipes_json = response.text.strip()
            print(f"📝 Raw Gemini response: {recipes_json}")
            
            # Clean up the response if it has markdown formatting
            if '```json' in recipes_json:
                recipes_json = recipes_json.split('```json')[1].split('```')[0].strip()
            elif '```' in recipes_json:
                recipes_json = recipes_json.split('```')[1].split('```')[0].strip()
            
            print(f"🧹 Cleaned JSON: {recipes_json}")
            recipes = json.loads(recipes_json)
            print(f"✅ Parsed {len(recipes)} recipes successfully")
            
            # Save recipes to MySQL
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                
                saved_recipes = []
                for recipe in recipes:
                    cursor.execute('''
                        INSERT INTO recipes (title, ingredients, instructions, prep_time, difficulty, source_ingredients)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (
                        recipe['title'],
                        json.dumps(recipe['ingredients']),
                        json.dumps(recipe['instructions']),
                        recipe['prep_time'],
                        recipe['difficulty'],
                        ingredients
                    ))
                    
                    recipe_id = cursor.lastrowid
                    recipe['id'] = recipe_id
                    recipe['source_ingredients'] = ingredients
                    saved_recipes.append(recipe)
                    print(f"💾 Saved recipe #{recipe_id}: {recipe['title']}")
                
                conn.commit()
                cursor.close()
                conn.close()
                print(f"✅ Successfully saved {len(saved_recipes)} recipes to database")
                
            except mysql.connector.Error as db_error:
                print(f"❌ Database Error: {db_error}")
                return jsonify({'error': f'Database error: {str(db_error)}'}), 500
            
            return jsonify({
                'success': True,
                'recipes': saved_recipes,
                'count': len(saved_recipes)
            })
            
        except json.JSONDecodeError as json_error:
            print(f"❌ JSON Parse Error: {json_error}")
            print(f"📝 Raw response causing error: {response.text}")
            return jsonify({
                'error': 'Failed to parse recipe data',
                'raw_response': response.text[:500]
            }), 500
        except mysql.connector.Error as db_error:
            print(f"❌ Database Error: {db_error}")
            return jsonify({'error': f'Database error: {str(db_error)}'}), 500
            
    except Exception as e:
        print(f"❌ General Server Error: {e}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/recipes', methods=['GET'])
def list_recipes():
    """Get all saved recipes"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute('''
            SELECT id, title, ingredients, instructions, prep_time, difficulty, 
                   source_ingredients, created_at 
            FROM recipes 
            ORDER BY created_at DESC
        ''')
        
        recipes = cursor.fetchall()
        
        # Parse JSON fields
        for recipe in recipes:
            recipe['ingredients'] = json.loads(recipe['ingredients'])
            recipe['instructions'] = json.loads(recipe['instructions'])
            recipe['created_at'] = recipe['created_at'].isoformat()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'recipes': recipes,
            'count': len(recipes)
        })
        
    except mysql.connector.Error as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@app.route('/api/recipes/<int:recipe_id>', methods=['GET'])
def get_recipe(recipe_id):
    """Get specific recipe by ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute('''
            SELECT id, title, ingredients, instructions, prep_time, difficulty, 
                   source_ingredients, created_at 
            FROM recipes 
            WHERE id = %s
        ''', (recipe_id,))
        
        recipe = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if recipe:
            recipe['ingredients'] = json.loads(recipe['ingredients'])
            recipe['instructions'] = json.loads(recipe['instructions'])
            recipe['created_at'] = recipe['created_at'].isoformat()
            return jsonify({'success': True, 'recipe': recipe})
        
        return jsonify({'error': 'Recipe not found'}), 404
        
    except mysql.connector.Error as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

@app.route('/api/models', methods=['GET'])
def list_models():
    """Debug: List available models"""
    try:
        models = genai.list_models()
        model_names = [model.name for model in models]
        return jsonify({'models': model_names})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM recipes')
        total_recipes = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'total_recipes': total_recipes,
            'database': 'connected',
            'environment': 'production' if not app.debug else 'development'
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'database': 'disconnected'
        }), 500

if __name__ == '__main__':
    print("🚀 Recipe API Server Starting...")
    
    # Check for required environment variables
    required_vars = ['GEMINI_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these before running the app!")
        exit(1)
    
    # Initialize database
    if not init_database():
        print("❌ Failed to initialize database. Exiting...")
        exit(1)
    
    print("📝 Endpoints:")
    print("   GET / - Frontend (index.html)")
    print("   POST /api/recipes - Generate recipes from ingredients")
    print("   GET /api/recipes - List all saved recipes")
    print("   GET /api/recipes/<id> - Get specific recipe")
    print("   GET /api/health - Health check")
    print("🗄️  Using MySQL database")
    print("🤖 Using Gemini 1.5 Flash")
    
    # Use PORT from environment (for cloud deployment) or default to 8002
    port = int(os.environ.get('PORT', 8002))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    
    app.run(debug=debug_mode, host='0.0.0.0', port=port)