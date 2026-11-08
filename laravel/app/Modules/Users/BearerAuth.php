<?php

namespace App\Modules\Users;

use App\Http\ApiProblem;
use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

final class BearerAuth
{
    public function __construct(private readonly JwtTokens $tokens) {}

    public function handle(Request $request, Closure $next, ?string $role = null): Response
    {
        $token = $request->bearerToken();
        if (! $token) {
            throw JwtTokens::unauthorized();
        }

        $user = User::find($this->tokens->subject($token));
        if ($user === null) {
            throw JwtTokens::unauthorized();
        }

        if ($role !== null && $user->role !== $role) {
            throw new ApiProblem(403, 'common.forbidden');
        }

        $request->setUserResolver(static fn () => $user);

        return $next($request);
    }
}
