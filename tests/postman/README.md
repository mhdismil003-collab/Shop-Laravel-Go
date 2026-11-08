# Shop Interview in Postman

## التجهيز السريع من Windows

شغّل Docker Desktop وافتح PowerShell في جذر المشروع:

```powershell
powershell -ExecutionPolicy Bypass -File .\Start-Shop.ps1
```

استورد ملفي `*ready.postman_collection.json` الموجودين في مجلد
`Postman-Ready` الناتج. تعمل المجموعتان دون اختيار Environment، وتحملان
بيانات العرض الصحيحة. مجموعة REST تتضمن 8 طلبات و13 تحققًا، ومجموعة
Operations تتضمن 23 طلبًا و28 تحققًا لإنشاء منتج بصورة وإضافة كمية وطلب
وإلغاء وإشعارات وصلاحيات. اختر صورة `demo-product.png` في الطلب 03 إذا
طلب Postman صلاحية الوصول إليها.

للتجهيز مرة أخرى دون البناء: `Prepare-Postman.ps1`.
لحالة السباق الفعلية: `Test-Race.ps1`.

[دليل التشغيل والمقابلة بالعربية](../../docs/INTERVIEW_GUIDE_AR.md) يشرح كل
طلب ونتيجته، واستيراد عقد gRPC، وإيقاف قاعدة المستودع وقاعدة التطبيق.

المجموعة الأصلية `shop-interview.postman_collection.json` ما زالت متاحة
لمن يريد استخدام Environment صريح. عند استخدامها استورد ملف البيئة
المولّد واختره أعلى اليمين قبل Run. لا تحتاجه المجموعتان الجديدتان.

## Full REST proof (Newman)

Use a disposable running Laravel Compose stack. The checked-in collection is
generated from the OpenAPI document served at `/openapi/v1.json`.

1. From this directory, run `npm ci --ignore-scripts` with Node 22 or later.
2. Copy `local.postman_environment.example.json` to `proof.local.json`.
   Set the configured demo admin email/password. Keep that file out of Git.
3. Run the security folder with local stock seeding.

```sh
SHOP_PROOF_ALLOW_WRITES=1 SHOP_PROOF_SEED_COMPOSE=1 npm run proof -- proof.local.json
```

PowerShell:

```powershell
$env:SHOP_PROOF_ALLOW_WRITES = '1'
$env:SHOP_PROOF_SEED_COMPOSE = '1'
npm run proof -- proof.local.json
```

The runner creates two customers and a product. The Compose option seeds one
unit via the warehouse's `stock-add` command. It then proves that customer B
gets 404 for customer A's order, that a customer gets 403 for changing status,
and that the admin can change it. Running the collection manually in Postman
requires adding one unit after the product is created.

Refresh the generated examples after changing the API:

```sh
npm run generate -- http://localhost:8080/openapi/v1.json
npm test
```
