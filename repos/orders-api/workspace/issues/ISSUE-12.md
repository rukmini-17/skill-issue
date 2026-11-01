# ISSUE-12: Big orders with a coupon are charged the wrong amount

Reported by: support, passing on a message from a wholesale customer

A customer says that when they order a lot of items and use their coupon, the
total looks too low. Finance thinks it is a rounding problem somewhere in
pricing, but nobody has checked. It might only happen on staging.

One example they sent: 12 units at 10.00 with a 10% coupon, not taxable. They
were charged 90.00. Our discount policy says the combined discount can never go
above the maximum in the pricing config.

No failing test yet. We need a clean reproduction before anyone changes code.
