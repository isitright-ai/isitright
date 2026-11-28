# Proposed fixture: pending owner review (written by Claude).
import pandas as pd

df = pd.read_csv("orders.csv")
north = df[df["region"] == "north"]["amount"].dropna()
result = {"north_mean": round(float(north.mean()), 2)}
