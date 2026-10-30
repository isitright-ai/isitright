-- NULL-count fixture.
--
-- Reference: SELECT COUNT(*) FROM shipments WHERE status = 'queued';
-- Candidate: SELECT COUNT(tracking_code) FROM shipments WHERE status = 'queued';

CREATE TABLE shipments (
    shipment_id INTEGER PRIMARY KEY,
    tracking_code TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'delivered'))
);

INSERT INTO shipments VALUES (1, NULL, 'queued');

