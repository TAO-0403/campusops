CREATE TABLE departments (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('requester', 'admin')),
    password_hash TEXT NOT NULL,
    department_id BIGINT REFERENCES departments(id),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((role = 'admin') OR department_id IS NOT NULL)
);

CREATE TABLE purchase_requests (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    vendor TEXT NOT NULL DEFAULT '',
    department_id BIGINT REFERENCES departments(id),
    amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (amount >= 0),
    currency CHAR(3) NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    requester_id BIGINT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'Draft'
        CHECK (status IN ('Draft', 'Submitted', 'Approved', 'Returned')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE request_events (
    id BIGSERIAL PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES purchase_requests(id) ON DELETE CASCADE,
    actor_id BIGINT NOT NULL REFERENCES users(id),
    event_type TEXT NOT NULL CHECK (event_type IN ('Created', 'Updated', 'Submitted')),
    previous_status TEXT CHECK (previous_status IS NULL OR previous_status IN ('Draft', 'Submitted', 'Approved', 'Returned')),
    new_status TEXT NOT NULL CHECK (new_status IN ('Draft', 'Submitted', 'Approved', 'Returned')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX purchase_requests_requester_created_idx
    ON purchase_requests (requester_id, created_at DESC);
CREATE INDEX purchase_requests_status_created_idx
    ON purchase_requests (status, created_at DESC);
CREATE INDEX request_events_request_created_idx
    ON request_events (request_id, created_at, id);

INSERT INTO departments (code, name) VALUES
    ('SCI', 'Science'),
    ('LIB', 'Library'),
    ('STU', 'Student Affairs'),
    ('OPS', 'Administration')
ON CONFLICT (code) DO NOTHING;
