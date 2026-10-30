-- Sum only per-record shortfalls whose two operands are known.
SELECT SUM(amount_owed - amount_collected) FROM tribute;
