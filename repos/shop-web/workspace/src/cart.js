/** @typedef {{sku: string, unitCents: number, qty: number}} CartItem */

export class Cart {
  constructor() {
    /** @type {CartItem[]} */
    this.items = [];
  }

  /** @param {CartItem} item */
  add(item) {
    if (!Number.isInteger(item.qty) || item.qty <= 0) {
      throw new RangeError('qty must be a positive integer');
    }
    const existing = this.items.find((i) => i.sku === item.sku);
    if (existing) {
      existing.qty += item.qty;
    } else {
      this.items.push({ ...item });
    }
  }

  /** @param {string} sku */
  remove(sku) {
    this.items = this.items.filter((i) => i.sku !== sku);
  }

  subtotalCents() {
    return this.items.reduce((sum, i) => sum + i.unitCents * i.qty, 0);
  }
}
