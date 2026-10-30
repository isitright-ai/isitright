PRAGMA foreign_keys = ON;

CREATE TABLE hubs (
    hub_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    zone TEXT NOT NULL CHECK (zone IN ('coastal', 'inland', 'mountain', 'metro'))
);

CREATE TABLE shipments (
    shipment_id INTEGER PRIMARY KEY,
    hub_id INTEGER NOT NULL REFERENCES hubs(hub_id),
    tracking_code TEXT UNIQUE,
    package_count INTEGER NOT NULL CHECK (package_count >= 1),
    declared_weight REAL CHECK (declared_weight >= 0),
    status TEXT NOT NULL CHECK (status IN ('queued', 'in_transit', 'delivered', 'cancelled')),
    shipped_at TEXT,
    delivered_at TEXT
);

CREATE TABLE couriers (
    courier_id INTEGER PRIMARY KEY,
    hub_id INTEGER REFERENCES hubs(hub_id),
    name TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1))
);

INSERT INTO hubs VALUES
    (1, 'HBR', 'coastal'),
    (2, 'RIV', 'inland'),
    (3, 'PIN', 'mountain');

INSERT INTO shipments VALUES
    (1, 1, 'PKG-A1', 12, 8.5, 'queued', NULL, NULL),
    (2, 2, 'PKG-B2', 7, 3.0, 'delivered', '2026-01-03', '2026-01-04'),
    (3, 3, 'PKG-C3', 15, 11.25, 'delivered', '2026-01-05', '2026-01-07');

INSERT INTO couriers VALUES
    (1, 1, 'Mara', 1),
    (2, 2, 'Ivo', 1),
    (3, 3, 'Sana', 0);

