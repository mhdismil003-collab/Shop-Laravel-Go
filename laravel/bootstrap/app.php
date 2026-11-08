<?php

use App\Http\ApiHeaders;
use App\Http\ApiProblem;
use App\Modules\Users\BearerAuth;
use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;
use Illuminate\Http\Exceptions\HttpResponseException;
use Illuminate\Http\Request;
use Illuminate\Validation\ValidationException;
use Symfony\Component\HttpKernel\Exception\HttpExceptionInterface;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        health: '/health',
        then: static function (): void {
            require __DIR__.'/../routes/web.php';
        },
    )
    ->withMiddleware(function (Middleware $middleware): void {
        $middleware->prepend(ApiHeaders::class);
        $middleware->alias(['shop.auth' => BearerAuth::class]);
    })
    ->withExceptions(function (Exceptions $exceptions): void {
        $exceptions->dontReport([ApiProblem::class]);
        $exceptions->render(function (Throwable $error, Request $request) {
            if (! $request->is('api/*', 'images/*')) {
                return null;
            }

            if ($error instanceof HttpResponseException) {
                return $error->getResponse();
            }

            if ($error instanceof ApiProblem) {
                return $error->response($request);
            }

            if ($error instanceof ValidationException) {
                return (new ApiProblem(422, 'common.validation_failed', 'Validation failed',
                    extra: ['errors' => $error->errors()]))->response($request);
            }

            if ($error instanceof HttpExceptionInterface) {
                $status = $error->getStatusCode();
                $code = match ($status) {
                    400 => 'common.bad_request',
                    404 => 'common.not_found',
                    405 => 'common.method_not_allowed',
                    413 => 'common.payload_too_large',
                    429 => 'common.too_many_requests',
                    default => 'common.error',
                };

                return (new ApiProblem($status, $code, headers: $error->getHeaders()))->response($request);
            }

            return (new ApiProblem(500, 'common.internal_error'))->response($request);
        });
    })->create();
