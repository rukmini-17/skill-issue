# data-quality-frameworks — detailed patterns and worked examples

## Patterns

### Pattern 3: dbt Data Tests

```yaml
# models/marts/core/_core__models.yml
version: 2

models:
  - name: fct_orders
    description: Order fact table
    tests:
      # Table-level tests
      - dbt_utils.recency:
          datepart: day
          field: created_at
          interval: 1
      - dbt_utils.at_least_one
      - dbt_utils.expression_is_true:
          expression: "total_amount >= 0"

    columns:
      - name: order_id
        description: Primary key
        tests:
          - unique
          - not_null

      - name: customer_id
        description: Foreign key to dim_customers
        tests:
          - not_null
          - relationships:
              to: ref('dim_customers')
              field: customer_id

      - name: order_status
        tests:
          - accepted_values:
              values:
                ["pending", "processing", "shipped", "delivered", "cancelled"]

      - name: total_amount
        tests:
          - not_null
          - dbt_utils.expression_is_true:
              expression: ">= 0"

      - name: created_at
        tests:
          - not_null
          - dbt_utils.expression_is_true:
              expression: "<= current_timestamp"

  - name: dim_customers
    columns:
      - name: customer_id
        tests:
          - unique
          - not_null

      - name: email
        tests:
          - unique
          - not_null
          # Custom regex test
          - dbt_utils.expression_is_true:
              expression: "email ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$'"
```

### Pattern 5: Data Contracts

```yaml
# contracts/orders_contract.yaml
apiVersion: datacontract.com/v1.0.0
kind: DataContract
metadata:
  name: orders
  version: 1.0.0
  owner: data-platform-team
  contact: data-team@contracts.example

info:
  title: Orders Data Contract
  description: Contract for order event data from the ecommerce platform
  purpose: Analytics, reporting, and ML features

servers:
  production:
    type: snowflake
    account: company.us-east-1
    database: ANALYTICS
    schema: CORE

terms:
  usage: Internal analytics only
  limitations: PII must not be exposed in downstream marts
  billing: Charged per query TB scanned

schema:
  type: object
  properties:
    order_id:
      type: string
      format: uuid
      description: Unique order identifier
      required: true
      unique: true
      pii: false

    customer_id:
      type: string
      format: uuid
      description: Customer identifier
      required: true
      pii: true
      piiClassification: indirect

    total_amount:
      type: number
      minimum: 0
      maximum: 100000
      description: Order total in USD

    created_at:
      type: string
      format: date-time
      description: Order creation timestamp
      required: true

    status:
      type: string
      enum: [pending, processing, shipped, delivered, cancelled]
      description: Current order status

quality:
  type: SodaCL
  specification:
    checks for orders:
      - row_count > 0
      - missing_count(order_id) = 0
      - duplicate_count(order_id) = 0
      - invalid_count(status) = 0:
          valid values: [pending, processing, shipped, delivered, cancelled]
      - freshness(created_at) < 24h

sla:
  availability: 99.9%
  freshness: 1 hour
  latency: 5 minutes
```
