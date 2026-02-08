from typing import List, Optional
from fastapi import HTTPException
import csv
import io
from datetime import datetime
from config.database import get_db_connection

def create_client(company_name: str, contact_name: Optional[str], email: Optional[str], 
                  phone: Optional[str], address: Optional[str], tax_id: Optional[str], 
                  notes: Optional[str]) -> dict:
    """Create a new client"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO clients
            (company_name, contact_name, email, phone, address, tax_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (company_name, contact_name, email, phone, address, tax_id, notes))
        
        client_id = cursor.lastrowid
        conn.commit()

        cursor.execute('SELECT * FROM clients WHERE id = ?', (client_id,))
        new_client = dict(cursor.fetchone())
        return new_client

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

def get_all_clients() -> List[dict]:
    """Get all clients"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM clients ORDER BY company_name')
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        if conn:
            conn.close()

def get_client_by_id(client_id: int) -> dict:
    """Get a single client by ID"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM clients WHERE id = ?', (client_id,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='Client not found')
        return dict(row)
    finally:
        if conn:
            conn.close()

def update_client(client_id: int, company_name: str, contact_name: Optional[str], 
                  email: Optional[str], phone: Optional[str], address: Optional[str], 
                  tax_id: Optional[str], notes: Optional[str]) -> dict:
    """Update an existing client"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if client exists
        cursor.execute('SELECT id FROM clients WHERE id = ?', (client_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=f'Client with ID {client_id} not found')
        
        # Validate email format if provided
        if email and '@' not in email:
            raise HTTPException(status_code=400, detail='Invalid email format')
        
        # Check for duplicate email (excluding current client)
        if email:
            cursor.execute(
                'SELECT id FROM clients WHERE email = ? AND id != ?',
                (email, client_id)
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=400, 
                    detail=f'Email {email} is already in use by another client'
                )
        
        # Check for duplicate tax_id (excluding current client)
        if tax_id:
            cursor.execute(
                'SELECT id FROM clients WHERE tax_id = ? AND id != ?',
                (tax_id, client_id)
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=400, 
                    detail=f'Tax ID {tax_id} is already in use by another client'
                )
        
        # Update client
        cursor.execute('''
            UPDATE clients 
            SET 
                company_name = ?, 
                contact_name = ?, 
                email = ?, 
                phone = ?, 
                address = ?, 
                tax_id = ?,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (company_name, contact_name, email, phone, address, tax_id, notes, client_id))
        
        conn.commit()
        
        cursor.execute('SELECT * FROM clients WHERE id = ?', (client_id,))
        updated_client = dict(cursor.fetchone())
        
        return updated_client
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Failed to update client: {str(e)}')
    finally:
        if conn:
            conn.close()

def delete_client(client_id: int) -> dict:
    """Delete a client"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM clients WHERE id = ?', (client_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail='Client not found')
        conn.commit()
        return {'message': 'Client deleted successfully'}
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Delete failed: {str(e)}')
    finally:
        if conn:
            conn.close()

async def import_clients_from_csv(file_content: bytes, filename: str, skip_duplicates: bool, current_user: dict) -> dict:
    """Import clients from CSV with full response structure"""
    conn = None
    errors = []
    
    try:
        # Decode file
        try:
            csv_text = file_content.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail='File must be UTF-8 encoded')
        
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        if not rows:
            raise HTTPException(status_code=400, detail='CSV file is empty')
        
        if 'company_name' not in rows[0]:
            raise HTTPException(
                status_code=400, 
                detail='Missing required column: company_name'
            )
        
        # Process clients
        conn = get_db_connection()
        cursor = conn.cursor()
        inserted = updated = skipped = 0
        
        for idx, row in enumerate(rows, start=2):
            company = row.get('company_name', '').strip()
            if not company:
                errors.append(f'Row {idx}: Skipped (empty company_name)')
                skipped += 1
                continue
            
            # Validate email
            email = row.get('email', '').strip()
            if email and '@' not in email:
                errors.append(f'Row {idx} ({company}): Invalid email format')
                skipped += 1
                continue
            
            # Check duplicates
            existing_id = None
            if row.get('tax_id'):
                cursor.execute('SELECT id FROM clients WHERE tax_id = ?', (row['tax_id'].strip(),))
                result = cursor.fetchone()
                if result:
                    existing_id = result['id']
            
            if not existing_id and email:
                cursor.execute('SELECT id FROM clients WHERE email = ?', (email,))
                result = cursor.fetchone()
                if result:
                    existing_id = result['id']
            
            # Handle duplicate
            if existing_id:
                if skip_duplicates:
                    errors.append(f'Row {idx} ({company}): Skipped (duplicate found)')
                    skipped += 1
                else:
                    cursor.execute('''
                        UPDATE clients SET contact_name = ?, phone = ?, address = ?, notes = ?
                        WHERE id = ?
                    ''', (
                        row.get('contact_name', '').strip(),
                        row.get('phone', '').strip(),
                        row.get('address', '').strip(),
                        row.get('notes', '').strip(),
                        existing_id
                    ))
                    updated += 1
                continue
            
            # Insert new client
            try:
                cursor.execute('''
                    INSERT INTO clients 
                    (company_name, contact_name, email, phone, address, tax_id, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    company,
                    row.get('contact_name', '').strip(),
                    email,
                    row.get('phone', '').strip(),
                    row.get('address', '').strip(),
                    row.get('tax_id', '').strip(),
                    row.get('notes', '').strip()
                ))
                inserted += 1
            except Exception as e:
                errors.append(f'Row {idx} ({company}): {str(e)[:80]}')
                skipped += 1
        
        conn.commit()
        
        return {
            'success': True,
            'summary': {
                'filename': filename,
                'total_rows': len(rows),
                'processed': inserted + updated + skipped,
                'inserted': inserted,
                'updated': updated,
                'skipped': skipped,
                'errors_count': len(errors)
            },
            'errors': errors,
            'audit_log': {
                'uploaded_by': current_user.get('sub', 'unknown'),
                'timestamp': datetime.now().isoformat(),
                'action': 'skip_duplicates' if skip_duplicates else 'overwrite_existing'
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        errors.append(f'System error: {str(e)[:100]}')
        raise HTTPException(status_code=500, detail=f'Import failed: {str(e)[:100]}')
    finally:
        if conn:
            conn.close()
