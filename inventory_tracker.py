import json
from datetime import datetime

class InventoryTracker:
    def __init__(self):
        self.items = {}

    def add_item(self, item_id: str, name: str, quantity: int, price: float):
        if item_id in self.items:
            self.items[item_id]["quantity"] += quantity
        else:
            self.items[item_id] = {
                "name": name,
                "quantity": quantity,
                "price": price,
                "created_at": datetime.now().isoformat(),
            }

    def remove_item(self, item_id: str, quantity: int) -> bool:
        if item_id not in self.items:
            raise KeyError(f"Item {item_id} does not exist")
        if quantity > self.items[item_id]["quantity"]:
            raise ValueError("Quantity to remove exceeds current stock")
        self.items[item_id]["quantity"] -= quantity
        return True

    def find_items_by_name(self, query: str) -> dict:
        q = query.lower()
        return {k: v for k, v in self.items.items() if q in v["name"].lower()}

    def get_low_stock(self, threshold: int = 5) -> dict:
        return {k: v for k, v in self.items.items() if v["quantity"] <= threshold}

    def calculate_total_value(self) -> float:
        total = 0.0
        for item in self.items.values():
            total += item["quantity"] * item["price"]
        return total

    def export_to_json(self, filepath: str):
        with open(filepath, "w") as f:
            json.dump(self.items, f, indent=4)


if __name__ == "__main__":
    tracker = InventoryTracker()
    tracker.add_item("item_1", "USB Cable", 10, 4.99)
    tracker.add_item("item_2", "Mechanical Keyboard", 2, 79.99)
    tracker.add_item("item_3", "Wireless Mouse", 3, 24.99)
    print("Initial Total Value:", tracker.calculate_total_value())
    
    try:
        tracker.remove_item("non_existent_item", 1)
    except KeyError as e:
        print("Caught expected KeyError:", e)

    try:
        tracker.remove_item("item_1", 15)
    except ValueError as e:
        print("Caught expected ValueError:", e)

    tracker.remove_item("item_1", 3)
    print("After removal, item_1 quantity:", tracker.items["item_1"]["quantity"])

    print("Search 'usb':", tracker.find_items_by_name("usb"))
    print("Low stock items:", tracker.get_low_stock(threshold=5))