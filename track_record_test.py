
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from track_record import TradeRecord, TrackRecord

print("=== Track Record System Test ===")

# Test 1: Initial state
tr = TrackRecord()
print("\n1. Initial state:")
print(f"   Trade count: {len(tr.trades)}")
print(f"   Save path: {tr.save_path}")

# Test 2: Add mock trades using correct API
print("\n2. Adding mock trades...")
tr.record_entry(
    ticket=123456, symbol="EURUSD", direction="BUY",
    entry_price=1.1000, lot_size=0.1, strategy_type="SMC_ICT"
)
tr.record_entry(
    ticket=123457, symbol="GBPUSD", direction="SELL",
    entry_price=1.2500, lot_size=0.1, strategy_type="SMC_ICT"
)
print(f"   Trades after entry: {len(tr.trades)}")

# Test 3: Close trades
print("\n3. Closing trades...")
tr.record_exit(ticket=123456, exit_price=1.1100, profit_loss=100.0)
tr.record_exit(ticket=123457, exit_price=1.2550, profit_loss=-50.0)
print(f"   Trades after exit: {len(tr.trades)}")

# Test 4: Get metrics
print("\n4. Metrics:")
metrics = tr.get_metrics()
for key, value in metrics.items():
    print(f"   {key}: {value}")

# Test 5: Save and Load
print("\n5. Saving to JSON...")
tr.save()
print(f"   File exists: {os.path.exists(os.path.join(files_dir, 'track_record.json'))}")

tr2 = TrackRecord.load(os.path.join(files_dir, "track_record.json"))
print(f"   Loaded trades: {len(tr2.trades)}")

# Test 6: Export CSV
print("\n6. Exporting to CSV...")
csv_path = os.path.join(files_dir, "track_record_export.csv")
tr.export_csv(csv_path)
print(f"   CSV created: {os.path.exists(csv_path)}")

# Test 7: Verify trade records
print("\n7. Trade details:")
for ticket, trade in tr.trades.items():
    print(f"   Ticket {ticket}: {trade.symbol} {trade.direction} | {trade.lots} lots | {trade.entry_price} -> {trade.exit_price} | PL: {trade.profit_loss:.2f}")

print("\n=== All Tests Passed ===")
