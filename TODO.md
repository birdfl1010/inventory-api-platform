# To-Do List
---
**🎨 ProdBranch Stock Settings Table (0/6 completed)**
- [ ] **Improve styling:**
    - [ ] Sortability
    - [ ] Filters (Drop-Down for BuyLine and PriceLine that are searchable)
    - [ ] Totals Table Footer
- [ ] **❗ Filters for actions ❗**
    - [ ] RSL Items to Review
    - [ ] Regionally Stocking VAP Items to Review
    - [ ] Manual Settings to Remove
    - [ ] Non-Moving Non-RSL Non-VAP Items to not stock

---

**Manual Setting Amount Limitation**
- [ ] **Implement Cost Limit to Setting Changes**
- [ ] **Implement Quantity Limit to Setting Changes**
- [ ] **Prevention of exceeding limit of manual settings**
---
**Endpoint for downloading ProdBranch Changes for Eclipse Upload**

---

**📔 Setting Change Log Integration (0/2 completed)**
- [ ] **Provide viewing ability of change log via front-end**
- [ ] **Implement commenting of changes by user at the time of changing settings...**
- [ ] **Integrate saving user during submission of settings table**
---
**Region Views Utilizing HTMX for loading table, to not slow down webpage loading**

---

**Long-term Items**

---

**☁️ Infrastructure & Cloud Migration (0/4 completed)**

1. **🐳 Docker & Database Migration**
    - [ ] **🔥 Move PostgreSQL to AWS RDS.**
        - [ ] ⏩ Prerequisite for AWS SQS & Lambda Integration.

2. **🔄 AWS SQS & Lambda Integration**
    - [ ] **Build SQS queue for change requests.**
    - [ ] **Develop Lambda to process SQS and update ERP.**
    - [ ] **Create Lambda to handle ERP success messages.**

---

**Implement Setting Change Reconcilliation**
- [ ] **Daily Data update also validated setting changes utilizing change-log data**
