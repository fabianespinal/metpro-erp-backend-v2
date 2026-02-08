from typing import List, Optional
from fastapi import HTTPException
import json
from datetime import datetime
from config.database import get_db_connection

def calculate_quote_totals(items: List[dict], charges: dict) -> dict:
    """
    METPRO CALCULATION ENGINE - PRESERVED EXACTLY
    Calculate all totals with discounts, charges, and ITBIS
    """
    # Calculate items total
    items_total = sum(float(item['quantity'] or 0) * float(item['unit_price'] or 0) for item in items)
    
    # Calculate total discounts
    total_discounts = 0
    for item in items:
        subtotal = float(item['quantity'] or 0) * float(item['unit_price'] or 0)
        if item.get('discount_type') == 'percentage':
            total_discounts += subtotal * (float(item.get('discount_value', 0)) / 100)
        elif item.get('discount_type') == 'fixed':
            total_discounts += float(item.get('discount_value', 0))
    
    items_after_discount = items_total - total_discounts
    
    # Get percentages safely with defaults
    supervision_pct = float(charges.get('supervision_percentage', 10.0))
    admin_pct = float(charges.get('admin_percentage', 4.0))
    insurance_pct = float(charges.get('insurance_percentage', 1.0))
    transport_pct = float(charges.get('transport_percentage', 3.0))
    contingency_pct = float(charges.get('contingency_percentage', 3.0))
    
    # Calculate charges
    supervision = items_after_discount * (supervision_pct / 100) if charges.get('supervision') else 0
    admin = items_after_discount * (admin_pct / 100) if charges.get('admin') else 0
    insurance = items_after_discount * (insurance_pct / 100) if charges.get('insurance') else 0
    transport = items_after_discount * (transport_pct / 100) if charges.get('transport') else 0
    contingency = items_after_discount * (contingency_pct / 100) if charges.get('contingency') else 0
    
    subtotal_general = items_after_discount + supervision + admin + insurance + transport + contingency
    itbis = subtotal_general * 0.18
    grand_total = subtotal_general + itbis
    
    return {
        'items_total': items_total,
        'total_discounts': total_discounts,
        'items_after_discount': items_after_discount,
        'supervision': supervision,
        'admin': admin,
        'insurance': insurance,
        'transport': transport,
        'contingency': contingency,
        'subtotal_general': subtotal_general,
        'itbis': itbis,
        'grand_total': grand_total
    }

def generate_quote_id() -> str:
    """Generate unique quote ID"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    return f'Q-{timestamp}'

def create_quote(client_id: int, project_name: Optional[str], notes: Optional[str],
                 items: List[dict], included_charges: dict) -> dict:
    """Create a new quote with items and calculations"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verify client exists
        cursor.execute('SELECT id FROM clients WHERE id = ?', (client_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail='Client not found')
        
        # Generate quote ID
        quote_id = generate_quote_id()
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        # Calculate totals
        totals = calculate_quote_totals(items, included_charges)
        
        # Insert quote
        cursor.execute('''
            INSERT INTO quotes 
            (quote_id, client_id, date, project_name, notes, status, 
             included_charges, total_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            quote_id,
            client_id,
            current_date,
            project_name,
            notes,
            'Draft',
            json.dumps(included_charges),
            totals['grand_total']
        ))
        
        # Insert quote items
        for item in items:
            cursor.execute('''
                INSERT INTO quote_items 
                (quote_id, product_name, quantity, unit_price, discount_type, discount_value)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                quote_id,
                item['product_name'],
                item['quantity'],
                item['unit_price'],
                item.get('discount_type', 'none'),
                item.get('discount_value', 0.0)
            ))
        
        conn.commit()
        
        # Fetch complete quote
        cursor.execute('SELECT * FROM quotes WHERE quote_id = ?', (quote_id,))
        quote = dict(cursor.fetchone())
        
        cursor.execute('SELECT * FROM quote_items WHERE quote_id = ?', (quote_id,))
        quote['items'] = [dict(row) for row in cursor.fetchall()]
        
        return quote
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Failed to create quote: {str(e)}')
    finally:
        if conn:
            conn.close()

def get_all_quotes(client_id: Optional[int] = None, status: Optional[str] = None) -> List[dict]:
    """Get all quotes with optional filters"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT q.*, c.company_name as client_name
            FROM quotes q
            JOIN clients c ON q.client_id = c.id
            WHERE 1=1
        '''
        params = []
        
        if client_id:
            query += ' AND q.client_id = ?'
            params.append(client_id)
        if status:
            query += ' AND q.status = ?'
            params.append(status)
        
        query += ' ORDER BY q.date DESC'
        cursor.execute(query, params)
        
        quotes = [dict(row) for row in cursor.fetchall()]
        return quotes
        
    finally:
        if conn:
            conn.close()

def get_quote_by_id(quote_id: str) -> dict:
    """Get a single quote with items"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM quotes WHERE quote_id = ?', (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise HTTPException(status_code=404, detail='Quote not found')
        
        quote = dict(quote)
        
        cursor.execute('SELECT * FROM quote_items WHERE quote_id = ?', (quote_id,))
        quote['items'] = [dict(row) for row in cursor.fetchall()]
        
        return quote
        
    finally:
        if conn:
            conn.close()

def update_quote_status(quote_id: str, status: str) -> dict:
    """Update quote status"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT quote_id FROM quotes WHERE quote_id = ?', (quote_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail='Quote not found')
        
        valid_statuses = ['Draft', 'Sent', 'Approved', 'Rejected', 'Invoiced']
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f'Invalid status. Must be one of: {valid_statuses}'
            )
        
        cursor.execute('''
            UPDATE quotes SET status = ? WHERE quote_id = ?
        ''', (status, quote_id))
        
        conn.commit()
        
        return {'message': 'Status updated successfully', 'quote_id': quote_id, 'status': status}
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Failed to update status: {str(e)}')
    finally:
        if conn:
            conn.close()

def delete_quote(quote_id: str) -> dict:
    """Delete a quote and its items"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Delete items first
        cursor.execute('DELETE FROM quote_items WHERE quote_id = ?', (quote_id,))
        
        # Delete quote
        cursor.execute('DELETE FROM quotes WHERE quote_id = ?', (quote_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail='Quote not found')
        
        conn.commit()
        return {'message': 'Quote deleted successfully'}
        
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Delete failed: {str(e)}')
    finally:
        if conn:
            conn.close()
