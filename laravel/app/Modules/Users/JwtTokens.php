<?php

namespace App\Modules\Users;

use App\Http\ApiProblem;
use DomainException;
use Firebase\JWT\JWT;
use Firebase\JWT\Key;
use Illuminate\Support\Str;
use LogicException;
use TypeError;
use UnexpectedValueException;

final class JwtTokens
{
    private readonly string $key;

    public function __construct()
    {
        $key = base64_decode((string) config('shop.jwt_key'), true);
        if ($key === false || strlen($key) < 32) {
            throw new LogicException('JWT_SIGNING_KEY must contain at least 32 base64-encoded random bytes.');
        }

        $this->key = $key;
    }

    public function issue(User $user): array
    {
        $now = time();
        $ttl = config('shop.jwt_seconds');

        return [
            'accessToken' => JWT::encode([
                'iss' => config('shop.jwt_issuer'), 'aud' => config('shop.jwt_audience'),
                'sub' => $user->id, 'role' => $user->role, 'iat' => $now, 'exp' => $now + $ttl,
            ], $this->key, 'HS256'),
            'tokenType' => 'Bearer',
            'expiresIn' => $ttl,
        ];
    }

    public function subject(string $token): string
    {
        try {
            $claims = JWT::decode($token, new Key($this->key, 'HS256'));
        } catch (DomainException | TypeError | UnexpectedValueException) {
            throw self::unauthorized();
        }

        if (($claims->iss ?? null) !== config('shop.jwt_issuer')
            || ($claims->aud ?? null) !== config('shop.jwt_audience')
            || ! is_int($claims->exp ?? null) || ! is_int($claims->iat ?? null)
            || ! is_string($claims->sub ?? null) || ! Str::isUuid($claims->sub)) {
            throw self::unauthorized();
        }

        return $claims->sub;
    }

    public static function unauthorized(): ApiProblem
    {
        return new ApiProblem(401, 'common.unauthorized', headers: ['WWW-Authenticate' => 'Bearer']);
    }
}
