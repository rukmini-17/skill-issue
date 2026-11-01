/**
 * @param {number} cents
 * @param {number} percent
 */
export function applyDiscount(cents, percent) {
  if (percent < 0 || percent > 100) {
    throw new RangeError('percent must be between 0 and 100');
  }
  return Math.round(cents * (1 - percent / 100));
}

/**
 * @param {number} cents
 * @param {number} rate
 */
export function addTax(cents, rate) {
  return cents + Math.round(cents * rate);
}

/**
 * @param {number} subtotalCents
 * @param {number} freeThresholdCents
 */
export function shippingCents(subtotalCents, freeThresholdCents) {
  return subtotalCents >= freeThresholdCents ? 0 : 599;
}
