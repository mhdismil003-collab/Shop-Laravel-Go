<?php

namespace App\Http;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use RuntimeException;
use Symfony\Component\HttpFoundation\Response;
use Throwable;

final class ApiProblem extends RuntimeException
{
    public function __construct(
        public readonly int $status,
        public readonly string $codeName,
        public readonly ?string $title = null,
        public readonly ?string $detail = null,
        public readonly array $extra = [],
        public readonly array $headers = [],
        ?Throwable $previous = null,
        private readonly ?string $userMessage = null,
    ) {
        parent::__construct($detail ?? $title ?? $codeName, previous: $previous);
    }

    public function response(Request $request): JsonResponse
    {
        return response()->json([
            'type' => 'https://shop.local/errors/'.str_replace('_', '-', explode('.', $this->codeName, 2)[1]),
            'title' => $this->title ?? Response::$statusTexts[$this->status] ?? 'Request failed',
            'status' => $this->status,
            'detail' => $this->detail,
            'instance' => $request->getPathInfo(),
            'code' => $this->codeName,
            'userMessage' => $this->userMessage ?? $this->messageForUser(),
            'traceId' => ApiHeaders::traceId($request),
        ] + $this->extra, $this->status, ['Content-Type' => 'application/problem+json'] + $this->headers);
    }
    private function messageForUser(): string
    {
        return match ($this->codeName) {
            'common.bad_request' => 'تعذّر قراءة الطلب. تحقّق من البيانات وأعد المحاولة.',
            'common.unauthorized' => 'انتهت الجلسة أو يلزم تسجيل الدخول للمتابعة.',
            'common.forbidden' => 'حسابك لا يملك صلاحية تنفيذ هذا الإجراء.',
            'common.not_found' => 'العنصر المطلوب غير موجود أو غير متاح لحسابك.',
            'common.method_not_allowed' => 'طريقة تنفيذ هذا الطلب غير مدعومة.',
            'common.validation_failed' => 'راجع الحقول المحددة وصحّح بياناتها.',
            'common.payload_too_large' => 'حجم البيانات المرسلة يتجاوز الحد المسموح.',
            'products.image_too_large' => 'حجم الصورة أكبر من الحد المسموح وهو 2 ميغابايت.',
            'common.unsupported_media_type', 'products.unsupported_image_type' => 'أرفق صورة سليمة بصيغة JPG أو PNG أو WebP.',
            'common.too_many_requests' => 'تجاوزت عدد محاولات تسجيل الدخول. انتظر قليلًا ثم حاول مجددًا.',
            'common.service_unavailable' => 'المستودع غير متاح مؤقتًا. حاول مجددًا بعد قليل.',
            'users.invalid_credentials' => 'بيانات الدخول غير صحيحة أو الحساب مقفل مؤقتًا.',
            'users.duplicate_email' => 'هذا البريد مسجّل بالفعل. سجّل الدخول إلى حسابك.',
            'products.not_found' => 'تعذّر العثور على المنتج المطلوب.',
            'products.stock_operation_conflict' => 'استُخدم معرّف الإضافة لعملية مختلفة. راجع الرصيد قبل إرسال عملية جديدة.',
            'products.stock_capacity' => 'تتجاوز هذه الإضافة الحد الأقصى لرصيد المنتج. أدخل كمية أصغر.',
            'products.image_not_found' => 'صورة المنتج غير متاحة.',
            'orders.not_found' => 'لم نجد هذا الطلب ضمن الطلبات المتاحة لحسابك.',
            'orders.insufficient_stock' => 'الكمية المتوفرة لا تكفي. لم يُنشأ الطلب.',
            'orders.invalid_status_transition' => 'هذا الانتقال غير متاح لحالة الطلب الحالية. حدّث الطلب وحاول مجددًا.',
            default => 'تعذّر إتمام العملية. حاول مجددًا أو شارك رقم التتبع مع المسؤول.',
        };
    }

}
