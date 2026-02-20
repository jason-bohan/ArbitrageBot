#!/usr/bin/env python3
"""
Simple debug test to check KalshiCommandCenter core functionality.
Tests the actual code without complex mocking.
"""

import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_bot_scripts():
    """Test BOT_SCRIPTS dictionary"""
    print("🔍 Testing BOT_SCRIPTS dictionary...")
    
    # Import the constant
    from KalshiCommandCenter import BOT_SCRIPTS
    
    print(f"📋 Total bots: {len(BOT_SCRIPTS)}")
    for key, script in BOT_SCRIPTS.items():
        print(f"  🤖 {key}: {script}")
    
    expected_bots = {
        "credit_spread": "KalshiCreditSpread.py",
        "iron_condor": "KalshiIronCondor.py", 
        "pairs": "KalshiPairs.py",
        "scanner": "KalshiScanner.py",
        "profit_maximizer": "ProfitMaximizer.py",
        "man_target_snipe": "KalshiManTargetSnipe.py",
    }
    
    if BOT_SCRIPTS == expected_bots:
        print("✅ BOT_SCRIPTS dictionary is correct")
        return True
    else:
        print("❌ BOT_SCRIPTS dictionary is missing bots:")
        missing = set(expected_bots.keys()) - set(BOT_SCRIPTS.keys())
        for bot in missing:
            print(f"  ❌ {bot}")
        return False

def test_imports():
    """Test that all bot scripts can be imported"""
    print("\n🔍 Testing bot script imports...")
    
    bot_files = [
        "KalshiCreditSpread.py",
        "KalshiIronCondor.py", 
        "KalshiPairs.py",
        "KalshiScanner.py",
        "ProfitMaximizer.py",
        "KalshiManTargetSnipe.py"
    ]
    
    for bot_file in bot_files:
        try:
            # Import the module
            module_name = bot_file.replace('.py', '')
            spec = __import__(module_name)
            print(f"  ✅ {bot_file} - Imported successfully")
            
            # Check if it has the expected class
            expected_classes = [
                "KalshiCreditSpreadBot",
                "KalshiIronCondorBot",
                "KalshiPairsBot", 
                "KalshiScannerBot",
                "ProfitMaximizerBot",
                "KalshiManTargetSnipeBot"
            ]
            
            if module_name in expected_classes:
                expected_class = module_name.replace('Kalshi', '').replace('Profit', 'Profit') + 'Bot'
                if hasattr(spec, expected_class):
                    print(f"    ✅ Has {expected_class} class")
                else:
                    print(f"    ❌ Missing {expected_class} class")
            
        except Exception as e:
            print(f"  ❌ {bot_file} - Import failed: {e}")
            return False
    
    return True

def test_update_bots_logic():
    """Test the update_bots_table logic directly"""
    print("\n🔍 Testing update_bots_table logic...")
    
    try:
        # Import the dashboard class
        from KalshiCommandCenter import KalshiDashboard, BOT_SCRIPTS
        
        # Create a mock dashboard instance without running the full app
        dashboard = KalshiDashboard()
        
        # Mock the required methods
        dashboard.bots = {}
        dashboard._bots_sort = ("bot", False)
        
        # Mock query_one to return our test objects
        class MockDataTable:
            def __init__(self):
                self.columns = []
                self.rows = []
                self.cleared_count = 0
            
            def add_columns(self, *cols):
                self.columns = list(cols)
                print(f"  ✅ Table columns added: {cols}")
            
            def clear(self):
                self.rows = []
                self.cleared_count += 1
                print(f"  ✅ Table cleared (call #{self.cleared_count})")
            
            def add_row(self, *row_data):
                self.rows.append(row_data)
                print(f"  ✅ Row added: {row_data}")
        
        class MockLog:
            def write_line(self, message):
                print(f"  📝 Log: {message}")
        
        class MockVertical:
            def __init__(self):
                self.children = []
            
            def mount(self, widget):
                self.children.append(widget)
                print(f"  🔧 Mounted: {type(widget).__name__}")
        
        # Override query_one method
        def mock_query_one(selector, *args):
            if selector == "#bots_table":
                return MockDataTable()
            elif selector == "#main_log":
                return MockLog()
            elif selector == "#bots_actions":
                return MockVertical()
            elif selector == "#status-strip":
                return MockStatic()
            else:
                raise ValueError(f"Unknown selector: {selector}")
        
        dashboard.query_one = mock_query_one
        
        # Test the update_bots_table method
        print("  🔄 Calling update_bots_table()...")
        dashboard.update_bots_table()
        
        print("  ✅ update_bots_table completed without errors")
        return True
        
    except Exception as e:
        print(f"  ❌ update_bots_table failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all debug tests"""
    print("🐛 Simple KalshiCommandCenter Debug Test")
    print("=" * 50)
    
    tests = [
        ("BOT_SCRIPTS Dictionary", test_bot_scripts),
        ("Bot Script Imports", test_imports),
        ("Update Bots Logic", test_update_bots_logic)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n🧪 Running: {test_name}")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 50)
    print("📊 SUMMARY:")
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} {test_name}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n🎉 All tests passed! The core logic is working.")
        print("💡 The issue is likely in the TUI rendering or CSS layout.")
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
