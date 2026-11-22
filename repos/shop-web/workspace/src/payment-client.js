export class PaymentClient {
  /**
   * @param {string} baseUrl
   * @param {string} apiKey
   * @param {typeof fetch} [fetchImpl]
   */
  constructor(baseUrl, apiKey, fetchImpl = fetch) {
    this.baseUrl = baseUrl;
    this.apiKey = apiKey;
    this.fetchImpl = fetchImpl;
  }

  /**
   * @param {number} amountCents
   * @param {string} orderId
   */
  async charge(amountCents, orderId) {
    const res = await this.fetchImpl(`${this.baseUrl}/charges`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${this.apiKey}` },
      body: JSON.stringify({ amountCents, orderId }),
    });
    if (!res.ok) {
      throw new Error(`charge failed with status ${res.status}`);
    }
    return res.json();
  }
}
