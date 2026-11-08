<?php

namespace App\Http;

use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Str;
use Symfony\Component\HttpFoundation\Response;

final class ApiHeaders
{
    public static function traceId(Request $request): string
    {
        if (! $request->attributes->has('shop.trace_id')) {
            $request->attributes->set('shop.trace_id', (string) Str::uuid());
        }

        return $request->attributes->get('shop.trace_id');
    }

    public function handle(Request $request, Closure $next): Response
    {
        $traceId = self::traceId($request);
        $response = $request->is('api/*') && $request->isJson() && $request->getContent() !== ''
            && ! json_validate($request->getContent())
            ? (new ApiProblem(400, 'common.bad_request', detail: 'Malformed JSON.'))->response($request)
            : $next($request);

        $headers = $response->headers;
        $headers->set('X-Content-Type-Options', 'nosniff');
        $headers->set('X-Frame-Options', 'DENY');
        $headers->set('Referrer-Policy', 'no-referrer');
        $headers->set('X-Request-ID', $traceId);
        $headers->remove('X-Powered-By');
        if ($request->is('api/*')) {
            $headers->set('Content-Security-Policy', "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'");
        }
        if ($request->is('/')) {
            $headers->set('Content-Security-Policy', "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; object-src 'none'");
        }
        if ($request->headers->has('Authorization') || $request->is('api/v1/auth/login')) {
            $headers->set('Cache-Control', 'no-store');
        }

        return $response;
    }
}
