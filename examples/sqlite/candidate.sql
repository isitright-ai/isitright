-- Sum each column independently, then subtract the totals.
SELECT SUM(amount_owed) - SUM(amount_collected) FROM tribute;
