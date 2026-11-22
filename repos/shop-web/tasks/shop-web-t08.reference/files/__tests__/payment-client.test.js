import { PaymentClient } from '../src/payment-client.js';

describe('PaymentClient', () => {
  it('should post a charge', async () => {
    const fetchImpl = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 'ch_1' }) });
    const client = new PaymentClient('http://payments.example/v1', 'test-key', fetchImpl);
    await expect(client.charge(500, 'o-1')).resolves.toEqual({ id: 'ch_1' });
  });
});
