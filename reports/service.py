from typing import Optional
from fastapi import HTTPException
from config.database import get_db_connection

def get_quotes_summary(start_date: Optional[str], end_date: Optional[str], 
                       client_id: Optional[int]) -> dict:
    """Quotes summary report: totals + status breakdown"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build query with filters
        query = '''
            SELECT 
                COUNT(*) as total_quotes,
                status,
                COUNT(*) as count
            FROM quotes
            WHERE 1=1
        '''
        params = []
        
        if start_date and end_date:
            query += ' AND date BETWEEN ? AND ?'
            params.extend([start_date, end_date])
        if client_id:
            query += ' AND client_id = ?'
            params.append(client_id)
        
        query += ' GROUP BY status ORDER BY status'
        cursor.execute(query, params)
        status_breakdown = [dict(row) for row in cursor.fetchall()]
        
        # Get grand total
        total_query = 'SELECT COUNT(*) as total FROM quotes WHERE 1=1'
        total_params = []
        if start_date and end_date:
            total_query += ' AND date BETWEEN ? AND ?'
            total_params.extend([start_date, end_date])
        if client_id:
            total_query += ' AND client_id = ?'
            total_params.append(client_id)
        
        cursor.execute(total_query, total_params)
        grand_total = cursor.fetchone()['total']
        
        return {
            'summary': {
                'total_quotes': grand_total,
                'filters': {
                    'start_date': start_date,
                    'end_date': end_date,
                    'client_id': client_id
                }
            },
            'status_breakdown': [
                {
                    'status': row['status'],
                    'count': row['count'],
                    'percentage': round((row['count'] / grand_total * 100), 1) if grand_total > 0 else 0
                }
                for row in status_breakdown
            ]
        }
    finally:
        if conn:
            conn.close()

def get_revenue_report(start_date: Optional[str], end_date: Optional[str],
                       client_id: Optional[int]) -> dict:
    """Revenue report: approved + invoiced totals"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT 
                status,
                COALESCE(SUM(total_amount), 0) as total_revenue,
                COUNT(*) as quote_count
            FROM quotes
            WHERE status IN ('Approved', 'Invoiced')
        '''
        params = []
        
        if start_date and end_date:
            query += ' AND date BETWEEN ? AND ?'
            params.extend([start_date, end_date])
        if client_id:
            query += ' AND client_id = ?'
            params.append(client_id)
        
        query += ' GROUP BY status ORDER BY status'
        cursor.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]
        
        # Get values safely
        approved = next((r for r in results if r['status'] == 'Approved'), 
                       {'total_revenue': 0, 'quote_count': 0})
        invoiced = next((r for r in results if r['status'] == 'Invoiced'), 
                       {'total_revenue': 0, 'quote_count': 0})
        
        return {
            'summary': {
                'filters': {
                    'start_date': start_date,
                    'end_date': end_date,
                    'client_id': client_id
                }
            },
            'revenue_breakdown': [
                {
                    'status': 'Approved (Ready to Invoice)',
                    'total_revenue': float(approved['total_revenue']),
                    'quote_count': approved['quote_count']
                },
                {
                    'status': 'Invoiced (Realized Revenue)',
                    'total_revenue': float(invoiced['total_revenue']),
                    'quote_count': invoiced['quote_count']
                }
            ],
            'grand_total': float(approved['total_revenue'] + invoiced['total_revenue'])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Revenue report failed: {str(e)[:100]}')
    finally:
        if conn:
            conn.close()

def get_client_activity(start_date: Optional[str], end_date: Optional[str]) -> dict:
    """Client activity report"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT 
                c.id as client_id,
                c.company_name,
                COUNT(q.quote_id) as quote_count,
                COALESCE(SUM(q.total_amount), 0) as total_quoted,
                MAX(q.date) as last_quote_date
            FROM clients c
            INNER JOIN quotes q ON c.id = q.client_id
            WHERE 1=1
        '''
        params = []
        
        if start_date and end_date:
            query += ' AND q.date IS NOT NULL AND q.date BETWEEN ? AND ?'
            params.extend([start_date, end_date])
        
        query += ' GROUP BY c.id, c.company_name ORDER BY total_quoted DESC'
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        clients_data = []
        for row in rows:
            clients_data.append({
                'client_id': row['client_id'],
                'client_name': row['company_name'] or 'Unknown',
                'quote_count': int(row['quote_count']) if row['quote_count'] else 0,
                'total_quoted': float(row['total_quoted']) if row['total_quoted'] else 0.0,
                'last_quote_date': row['last_quote_date']
            })
        
        return {
            'summary': {
                'total_clients': len(clients_data),
                'filters': {
                    'start_date': start_date,
                    'end_date': end_date
                }
            },
            'clients': clients_data
        }
    finally:
        if conn:
            conn.close()
