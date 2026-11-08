<?php

namespace App\Modules\Users;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Foundation\Auth\User as Authenticatable;

final class User extends Authenticatable
{
    use HasUuids;

    protected $fillable = ['email', 'password', 'role'];

    protected $hidden = ['password', 'failed_attempts', 'locked_until'];

    protected function casts(): array
    {
        return ['locked_until' => 'immutable_datetime', 'failed_attempts' => 'integer'];
    }
}
