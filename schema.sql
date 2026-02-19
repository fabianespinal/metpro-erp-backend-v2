-- ==================== USERS TABLE ====================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT UNIQUE,
    full_name TEXT,
    role TEXT DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ==================== CLIENTS TABLE ====================
CREATE TABLE IF NOT EXISTS clients (
    id SERIAL PRIMARY KEY,
    company_name TEXT NOT NULL,
    contact_name TEXT,
    email TEXT UNIQUE,
    phone TEXT,
    address TEXT,
    tax_id TEXT UNIQUE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ==================== PRODUCTS TABLE ====================
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    unit_price NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ==================== QUOTES TABLE ====================
CREATE TABLE IF NOT EXISTS quotes (
    id SERIAL PRIMARY KEY,
    quote_id TEXT UNIQUE NOT NULL,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    project_name TEXT,
    notes TEXT,
    status TEXT DEFAULT 'Draft',
    included_charges JSONB NOT NULL,
    total_amount NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ==================== QUOTE ITEMS TABLE ====================
CREATE TABLE IF NOT EXISTS quote_items (
    id SERIAL PRIMARY KEY,
    quote_id TEXT NOT NULL REFERENCES quotes(quote_id) ON DELETE CASCADE,
    product_name TEXT NOT NULL,
    quantity NUMERIC(12,2) NOT NULL,
    unit_price NUMERIC(12,2) NOT NULL,
    discount_type TEXT DEFAULT 'none',
    discount_value NUMERIC(12,2) DEFAULT 0.0
);

-- ==================== INVOICES TABLE ====================
CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    quote_id TEXT UNIQUE NOT NULL REFERENCES quotes(quote_id) ON DELETE CASCADE,
    invoice_number TEXT UNIQUE NOT NULL,
    invoice_date DATE NOT NULL,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    total_amount NUMERIC(12,2) NOT NULL,
    status TEXT DEFAULT 'Pending',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ==================== PROJECTS TABLE ====================
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'planning',
    start_date DATE NOT NULL,
    end_date DATE,
    estimated_budget NUMERIC(12,2),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ==================== CONTACTS TABLE ====================
CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ==================== INDEXES ====================
CREATE INDEX IF NOT EXISTS idx_clients_email ON clients(email);
CREATE INDEX IF NOT EXISTS idx_clients_tax_id ON clients(tax_id);

CREATE INDEX IF NOT EXISTS idx_quotes_client_id ON quotes(client_id);
CREATE INDEX IF NOT EXISTS idx_quotes_status ON quotes(status);
CREATE INDEX IF NOT EXISTS idx_quotes_date ON quotes(date);

CREATE INDEX IF NOT EXISTS idx_quote_items_quote_id ON quote_items(quote_id);

CREATE INDEX IF NOT EXISTS idx_invoices_client_id ON invoices(client_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);

CREATE INDEX IF NOT EXISTS idx_projects_client_id ON projects(client_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

-- ==================== DEFAULT ADMIN USER ====================
INSERT INTO users (username, password_hash, email, full_name, role, is_active)
VALUES (
    'admin',
    '$argon2id$v=19$m=65536,t=3,p=4$c2FsdFNhbHRTYWx0$Z0u7xJq6u7xY1l0u7xJq6u7xY1l0u7xJq6u7xY1l0u7xJq6u7xY1l0u7xJq6u7xY1l0',
    'admin@metpro.com',
    'System Administrator',
    'admin',
    TRUE
)
ON CONFLICT (username) DO NOTHING;

INSERT INTO users (username, password_hash, email, full_name, role, is_active)
VALUES (
    'manager',
    '$argon2id$v=19$m=65536,t=3,p=4$N2J1d0p3b0p3b0p3b0p3bQ$1xq0p0Fq3uYxq2Q9V5m7p6u4z8T0xq1F5u6p7x9y2Q',
    'manager@metpro.com',
    'Manager User',
    'manager',
    TRUE
)
ON CONFLICT (username) DO NOTHING;