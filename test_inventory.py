import pytest  # or use standard unittest
from inventory_tracker import InventoryTracker  # import your class name


def test_remove_item_non_existent():
    tracker = InventoryTracker()
    # Check if KeyError is raised (or if it returns False, depending on implementation)
    with pytest.raises(KeyError):
        tracker.remove_item("NonExistentItem")


def test_remove_item_prevent_negative_quantity():
    tracker = InventoryTracker()
    tracker.add_item("Apple", quantity=3)

    # Attempting to remove more than available should raise ValueError or fail
    with pytest.raises(ValueError):
        tracker.remove_item("Apple", quantity=5)

    # Quantity should remain at 3, not go below 0
    assert tracker.get_quantity("Apple") == 3


def test_find_items_by_name_case_insensitive():
    tracker = InventoryTracker()
    tracker.add_item("Red Apple")
    tracker.add_item("Green Apple")
    tracker.add_item("Banana")

    results = tracker.find_items_by_name("apPLe")
    names = [item["name"] for item in results]

    assert len(results) == 2
    assert "Red Apple" in names
    assert "Green Apple" in names


def test_get_low_stock():
    tracker = InventoryTracker()
    tracker.add_item("Low Stock Item", quantity=2)
    tracker.add_item("Threshold Item", quantity=5)
    tracker.add_item("High Stock Item", quantity=10)

    low_stock = tracker.get_low_stock(threshold=5)
    names = [item["name"] for item in low_stock]

    assert "Low Stock Item" in names
    assert "Threshold Item" in names
    assert "High Stock Item" not in names