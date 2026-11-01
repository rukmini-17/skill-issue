import 'dotenv/config';
import express from 'express';
import _ from 'lodash';
import { readFileSync } from 'node:fs';
import { Cart } from './cart.js';
import { addTax, shippingCents } from './pricing.js';

const config = JSON.parse(readFileSync('config/app.json', 'utf8'));
const app = express();
app.use(express.json());

app.post('/quote', (req, res) => {
  const cart = new Cart();
  for (const item of _.castArray(req.body.items)) {
    cart.add(item);
  }
  const subtotal = cart.subtotalCents();
  const shipping = shippingCents(subtotal, config.freeShippingThreshold);
  res.json({ subtotal, shipping, total: addTax(subtotal, config.taxRate) + shipping });
});

app.listen(Number(process.env.PORT ?? 3000));
