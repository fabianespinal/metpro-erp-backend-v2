from typing import List
from fastapi import HTTPException
import csv
import io
from config.database import get_db_connection

def create_product(name: str, description: str, unit_price: float) -> dict:
    """Create a new product"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO products (name, description, unit_price)
            VALUES (?, ?, ?)
        ''', (name, description, unit_price))
        
        product_id = cursor.lastrowid
        conn.commit()

        cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
        new_product = dict(cursor.fetchone())
        return new_product

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

def get_all_products() -> List[dict]:
    """Get all products"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM products ORDER BY name')
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        if conn:
            conn.close()

def get_product_by_id(product_id: int) -> dict:
    """Get a single product by ID"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='Product not found')
        return dict(row)
    finally:
        if conn:
            conn.close()

def update_product(product_id: int, name: str, description: str, unit_price: float) -> dict:
    """Update an existing product"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM products WHERE id = ?', (product_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail='Product not found')
        
        cursor.execute('''
            UPDATE products 
            SET name = ?, description = ?, unit_price = ?
            WHERE id = ?
        ''', (name, description, unit_price, product_id))
        
        conn.commit()
        
        cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
        updated_product = dict(cursor.fetchone())
        return updated_product
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Failed to update product: {str(e)}')
    finally:
        if conn:
            conn.close()

def delete_product(product_id: int) -> dict:
    """Delete a product"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM products WHERE id = ?', (product_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail='Product not found')
        conn.commit()
        return {'message': 'Product deleted successfully'}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Delete failed: {str(e)}')
    finally:
        if conn:
            conn.close()

async def import_products_from_csv(file_content: bytes, filename: str) -> dict:
    """Import products from CSV"""
    conn = None
    try:
        # Decode file
        try:
            csv_text = file_content.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail='File must be UTF-8 encoded')
        
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        if not rows:
            raise HTTPException(status_code=400, detail='CSV file is empty')
        
        required_cols = ['name', 'unit_price']
        if not all(col in rows[0] for col in required_cols):
            raise HTTPException(
                status_code=400,
                detail=f'Missing required columns: {required_cols}'
            )
        
        conn = get_db_connection()
        cursor = conn.cursor()
        imported = 0
        skipped = 0
        
        for row in rows:
            name = row.get('name', '').strip()
            if not name:
                skipped += 1
                continue
            
            try:
                unit_price = float(row.get('unit_price', 0))
            except ValueError:
                skipped += 1
                continue
            
            description = row.get('description', '').strip()
            
            # Check if product exists
            cursor.execute('SELECT id FROM products WHERE name = ?', (name,))
            existing = cursor.fetchone()
            
            if existing:
                # Update existing
                cursor.execute('''
                    UPDATE products SET description = ?, unit_price = ?
                    WHERE name = ?
                ''', (description, unit_price, name))
            else:
                # Insert new
                cursor.execute('''
                    INSERT INTO products (name, description, unit_price)
                    VALUES (?, ?, ?)
                ''', (name, description, unit_price))
                imported += 1
        
        conn.commit()
        
        return {
            'imported': imported,
            'skipped': skipped,
            'total': len(rows)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Import failed: {str(e)}')
    finally:
        if conn:
            conn.close()
