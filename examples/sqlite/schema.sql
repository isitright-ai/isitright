CREATE TABLE tribute (
    tribute_id INTEGER PRIMARY KEY,
    province TEXT NOT NULL,
    amount_owed REAL CHECK (amount_owed >= 0),
    amount_collected REAL CHECK (amount_collected >= 0)
);
