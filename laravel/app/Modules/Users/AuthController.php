<?php

namespace App\Modules\Users;

use App\Http\ApiProblem;
use Illuminate\Database\UniqueConstraintViolationException;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Hash;
use Illuminate\Validation\Rules\Password;

final class AuthController
{
    private const DUMMY_HASH = '$2y$12$BYuVIQwC8yugVq4DSe4THevoPOQIyGvGB0JgyphZp8BtSN0PArJhS';

    public function register(Request $request): JsonResponse
    {
        $data = $request->validate([
            'email' => ['required', 'email:rfc', 'max:254'],
            'password' => ['bail', 'required', 'string', Password::min(8)->mixedCase()->numbers()->symbols(),
                static function (string $attribute, string $value, \Closure $fail): void {
                    if (strlen($value) > 72 || str_contains($value, "\0")) {
                        $fail('The password must be at most 72 bytes and contain no null characters.');
                    }
                },
            ],
        ]);

        try {
            $user = User::create([
                'email' => strtolower($data['email']),
                'password' => Hash::make($data['password']),
                'role' => 'Customer',
            ]);
        } catch (UniqueConstraintViolationException) {
            throw new ApiProblem(409, 'users.duplicate_email', detail: 'An account already uses this email.');
        }

        return response()->json(['id' => $user->id, 'email' => $user->email, 'role' => $user->role], 201);
    }

    public function login(Request $request, JwtTokens $tokens): JsonResponse
    {
        $email = $request->input('email');
        $password = $request->input('password');
        if (! is_string($email) || ! is_string($password) || strlen($email) > 254 || strlen($password) > 72
            || str_contains($email, "\0") || str_contains($password, "\0")) {
            throw $this->invalidCredentials();
        }

        $user = DB::transaction(function () use ($email, $password): ?User {
            $user = User::where('email', strtolower($email))->lockForUpdate()->first();
            $matches = Hash::check($password, $user?->password ?? self::DUMMY_HASH);
            if ($user === null || $user->locked_until?->isFuture()) {
                return null;
            }

            if ($user->locked_until !== null) {
                $user->failed_attempts = 0;
                $user->locked_until = null;
            }

            if (! $matches) {
                $user->failed_attempts++;
                if ($user->failed_attempts >= 5) {
                    $user->locked_until = now()->addMinutes(5);
                }
                $user->save();

                return null;
            }

            $user->failed_attempts = 0;
            $user->save();

            return $user;
        });

        if ($user === null) {
            throw $this->invalidCredentials();
        }

        return response()->json($tokens->issue($user));
    }

    public function me(Request $request): JsonResponse
    {
        $user = $request->user();

        return response()->json(['id' => $user->id, 'email' => $user->email, 'roles' => [$user->role]]);
    }

    private function invalidCredentials(): ApiProblem
    {
        return new ApiProblem(401, 'users.invalid_credentials', 'Invalid credentials');
    }
}
