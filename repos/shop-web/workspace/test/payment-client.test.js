import test from 'node:test';
import assert from 'node:assert/strict';
import { PaymentClient } from '../src/payment-client.js';

test('posts a charge and returns the body', async () => {
  const fakeFetch = async () => new Response(JSON.stringify({ id: 'ch_1' }), { status: 200 });
  const client = new PaymentClient('http://payments.example/v1', 'test-key', fakeFetch);
  assert.deepEqual(await client.charge(500, 'o-1'), { id: 'ch_1' });
});

test('throws on a failed charge', async () => {
  const fakeFetch = async () => new Response('', { status: 402 });
  const client = new PaymentClient('http://payments.example/v1', 'test-key', fakeFetch);
  await assert.rejects(client.charge(500, 'o-1'), /status 402/);
});
