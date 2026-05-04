# CHANGELOG - Backend Django AgriRipeness

Todos los cambios notables en este proyecto serán documentados en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
y este proyecto adhiere a [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Pendiente para Sprint 2+
- Modularización de views.py (3,100 líneas → 5 módulos)
- Modularización de serializers.py (1,100 líneas → 5 módulos)
- Tests unitarios (objetivo: >80% coverage)
- Documentación OpenAPI/Swagger
- Eliminar código legacy (history, JSONStringField)
- Instalar Redis en Railway para cache óptimo (opcional)

---

## [1.2.1] - 2025-11-12 - HOTFIXES CRÍTICOS + HARDENING

### 🚨 HOTFIXES DE PRODUCCIÓN

#### Fixed - Redis Connection Error (500 en todos los endpoints)
- **[CACHE]** Error crítico: `ConnectionInterrupted: Error 111 connecting to 127.0.0.1:6379`
  - **Impacto**: 500 en TODOS los endpoints (login, workers, password change)
  - **Causa**: settings.py intentaba conectar a Redis inexistente en Railway
  - **Solución**: Cache adaptativo basado en variable `REDIS_URL`
  - **Commits**: 
    - `hotfix(deps): Agregar django-redis para cache en producción`
    - `hotfix(cache): Usar LocMem si Redis no disponible`

#### Changed - Cache Strategy (Arquitectura Resiliente)
```python
# ANTES (ROTO)
if DEBUG and not USE_REDIS:
    CACHES = LocMemCache
else:
    CACHES = RedisCache  # ❌ Asumía que Redis existe

# DESPUÉS (RESILIENTE)
if REDIS_URL:  # Solo si Redis está configurado
    CACHES = RedisCache
else:
    CACHES = LocMemCache  # Fallback seguro
```

**Decisión Arquitectónica**: Cache adaptativo sin dependencia hard en Redis
- ✅ Railway sin Redis → LocMem (funcional)
- ✅ Railway con Redis → Redis (óptimo)
- ✅ Dev local → LocMem (default)
- ✅ Dev con Redis → Redis (si REDIS_URL en .env)

#### Fixed - Missing django-redis Dependency
- **[DEPS]** `ModuleNotFoundError: No module named 'django_redis'`
  - **Causa**: settings.py usaba `django_redis.cache.RedisCache` pero no estaba en requirements.txt
  - **Solución**: Agregado `django-redis>=5.0.0`
  - **Aprendizaje**: Siempre agregar dependencias ANTES de usarlas en código

#### Changed - DEBUG Default Value (Production Safety)
- **[CONFIG]** DEBUG ahora es `False` por defecto
  - **ANTES**: `DEBUG = os.environ.get("DEBUG", "True") == "True"` (inseguro)
  - **DESPUÉS**: `DEBUG = os.environ.get("DEBUG", "False") == "True"` (seguro)
  - **Impacto**: Stack traces no expuestos en producción
  - **Dev**: Configurar explícitamente `DEBUG=True` en `.env` local

#### Added - Endpoint Legacy /api/users/me/
- **[COMPATIBILITY]** Alias de `/api/me/` para compatibilidad frontend
  - **Razón**: Prevenir 404 si frontend usa ruta legacy
  - **Comportamiento**: Ambos endpoints apuntan a misma vista
  - **Testing**: Validado en producción (200 OK con auth, 401 sin auth)

#### Improved - Hugging Face API Logging
- **[LOGGING]** Logs estructurados con prefijos `[HF-*]`
  - **ANTES**: `print()` statements sin contexto
  - **DESPUÉS**: `sync_logger` con información detallada
  - **Prefijos**:
    - `[HF-SUCCESS]`: Detección exitosa
    - `[HF-FALLBACK-FAILED]`: Error de API
    - `[HF-SERVICE-UNAVAILABLE]`: Módulo no encontrado
    - `[HF-EXCEPTION]`: Error inesperado
  - **Incluye**: Tipo de error, acción sugerida, métricas (lemons, confidence, processing time)

### 📋 Decisiones Arquitectónicas Auditadas

#### 1. Gestión de Cache (CRÍTICA)
**Criterio**: Resiliencia sobre performance óptima
- **Política**: Cache NUNCA debe causar 500 errors
- **Implementación**: Fallback automático a LocMem si Redis no disponible
- **Trade-offs**:
  - ✅ Ventaja: Backend funciona sin Redis
  - ⚠️ Trade-off: LocMem no es persistente entre instancias (ok para staging)
  - 🎯 Futuro: Instalar Redis en Railway para cache distribuido

**Variables de Entorno**:
```bash
# Para usar Redis (opcional)
REDIS_URL=redis://user:pass@host:port/db

# Para dev local
DEBUG=True  # Fuerza LocMem por defecto
```

#### 2. Compatibilidad de Rutas (CRÍTICA)
**Criterio**: Backward compatibility sin breaking changes
- **Política**: Endpoints legacy mantienen misma funcionalidad
- **Implementación**: Alias en urls.py apuntando a mismas vistas

**Mapeo de Rutas**:
| Ruta Nueva | Ruta Legacy | Vista | Status |
|------------|-------------|-------|--------|
| `/api/auth/login/` | `/api/login/` | `views.login` | ✅ Ambas activas |
| `/api/auth/change-password/` | `/api/password-change/` | `views.password_change` | ✅ Ambas activas |
| `/api/users/me/` | `/api/me/` | `views.profile` | ✅ Ambas activas |

**Decisión**: No deprecar rutas legacy hasta Sprint 3+ (después de migración frontend confirmada)

#### 3. HTTP Status Codes Policy (QA-FRIENDLY)
**Criterio**: Códigos de error descriptivos para diagnóstico rápido

**Policy de Status Codes**:
```
200 OK: Operación exitosa
400 Bad Request: Payload inválido (error de cliente)
  - Credenciales inválidas
  - Campos faltantes/incorrectos
  - Validación de datos falla

401 Unauthorized: Sin autenticación o token inválido
  - Token expirado
  - Token faltante
  - Token malformado

403 Forbidden: Autenticado pero sin permisos
  - Tipo de usuario incorrecto para endpoint
  - Intento de admin en /api/workers/login/
  - Worker intentando acceder a endpoint de admin

404 Not Found: Endpoint no existe
  - Ruta incorrecta
  - Recurso no encontrado

500 Internal Server Error: Error del servidor
  - NUNCA debe ocurrir por cache/Redis
  - NUNCA debe exponer stack trace (DEBUG=False)
```

**Integración Cliente Resiliente**:
```javascript
// Recomendación para frontend
try {
  const response = await fetch('/api/auth/login/', {...});
  
  if (response.status === 403) {
    // Usuario correcto, endpoint incorrecto
    const data = await response.json();
    console.log(data.hint); // "Use /api/auth/login/ para admins"
    // Redirigir a endpoint correcto
  }
  
  if (response.status === 401) {
    // Token inválido o credenciales incorrectas
    // Redirigir a login
  }
  
  if (response.status === 400) {
    // Validación de payload
    const errors = await response.json();
    // Mostrar errores específicos al usuario
  }
  
} catch (error) {
  // Error de red o 500
  // Mostrar mensaje genérico, no reintentar
}
```

#### 4. Login Multirol (CRÍTICA)
**Criterio**: Endpoints separados por tipo de usuario para claridad

**Arquitectura**:
```
Admin/Superadmin → /api/auth/login/
  ├─ Accept: email + password
  ├─ Return: role="admin"|"superadmin"
  └─ JWT tokens (access + refresh)

Worker → /api/workers/login/
  ├─ Accept: email + password (primera vez)
  ├─ O: email + pin (login normal)
  ├─ Return: role="worker", api_key_prefix, pin_configured
  └─ JWT tokens (access + refresh)
```

**Request/Response QA-Friendly**:

```json
// Admin Login
POST /api/auth/login/
{
  "email": "admin@example.com",
  "password": "SecurePass123!"
}

Response 200:
{
  "user": {
    "id": 1,
    "role": "admin",
    "password_change_required": false
  },
  "access": "JWT_TOKEN",
  "refresh": "JWT_TOKEN"
}

// Worker Login (Primera vez)
POST /api/workers/login/
{
  "email": "worker@example.com",
  "password": "TempPass123"
}

Response 200:
{
  "user": {
    "id": 5,
    "role": "worker",
    "api_key_prefix": "AGR-WORKER-XXX...",
    "password_change_required": true,
    "pin_configured": false
  },
  "access": "JWT_TOKEN",
  "refresh": "JWT_TOKEN"
}

// Worker Login (Con PIN)
POST /api/workers/login/
{
  "email": "worker@example.com",
  "pin": "1234"
}

// Admin en Worker Endpoint (ERROR DESCRIPTIVO)
POST /api/workers/login/
{"email": "admin@example.com", "password": "xxx"}

Response 403:
{
  "detail": "Tipo de usuario incorrecto para este endpoint",
  "hint": "Este endpoint es solo para workers. Los administradores deben usar /api/auth/login/",
  "user_type_detected": "admin"
}
```

### 🧪 Testing & Validación

**Scripts de Testing**:
- `test_qa_support.py`: Validación QA completa (6 tests)
- `test_final_complete.py`: Validación post-deploy (6 tests)
- `test_with_correct_credentials.py`: Testing end-to-end con credenciales reales

**Cobertura Validada**:
- ✅ Health check
- ✅ Login admin/worker con credenciales correctas
- ✅ Password change sin confirm_password
- ✅ Validación de roles (403 para tipo incorrecto)
- ✅ Endpoints legacy funcionando
- ✅ Cache sin errores (LocMem activo)
- ✅ Autenticación JWT end-to-end

**Resultados**: 100% passing (18/18 tests)

### 🔧 Archivos Modificados

**Configuración**:
- `agriripeness_api/settings.py`: Cache adaptativo, DEBUG=False default
- `requirements.txt`: django-redis>=5.0.0

**Código**:
- `users/urls.py`: Rutas alias (/api/auth/*, /api/users/me/)
- `users/views.py`: Validación de roles, logging HF mejorado
- `users/serializers.py`: confirm_password opcional

**Documentación**:
- `API_ENDPOINTS_DOCUMENTATION.md`: Guía completa de API
- `BACKEND_TEAM_INSTRUCTIONS.md`: Instrucciones para equipo
- `CHANGELOG.md`: Este archivo

### 📊 Métricas de Calidad

**Commits**: 6 (14 totales en Sprint 1)
**Hotfixes**: 2 críticos
**Tests**: 100% passing
**Uptime**: 100% post-hotfix
**Status Codes**: Policy documentada
**Breaking Changes**: 0

### 🏷️ Etiquetas
- `QA-Critical-Fix`
- `Backend-Hardening`
- `Production-Safety`
- `Logging-Improvement`

---

## [1.2.0] - 2025-11-12 - QA SUPPORT

### 🎯 SOPORTE CRÍTICO PARA QA/TESTING

#### Changed - Password Change Flexibility
- **[PASSWORD]** `confirm_password` ahora es OPCIONAL en `/api/auth/change-password/`
  - **ANTES**: `{current_password, new_password, confirm_password}` (3 campos requeridos)
  - **AHORA**: `{current_password, new_password}` O `{current_password, new_password, confirm_password}`
  - **Razón**: Compatibilidad con diferentes implementaciones de frontend
  - **Comportamiento**: 
    - Si se provee `confirm_password`, se valida que coincida con `new_password`
    - Si se omite, se asume que frontend ya validó (se registra log de advertencia)
  - **Evidencia**:
    ```json
    // Request válido SIN confirmación
    POST /api/auth/change-password/
    {"current_password": "Old123", "new_password": "New123!"}
    
    // Request válido CON confirmación
    POST /api/auth/change-password/
    {"current_password": "Old123", "new_password": "New123!", "confirm_password": "New123!"}
    ```
  - **Commit**: `fix: Hacer confirm_password opcional para compatibilidad QA`

#### Added - User Type Validation
- **[AUTH]** Validación de tipo de usuario en `/api/workers/login/`
  - **Comportamiento**: Si un admin/superadmin intenta login en endpoint de workers, recibe 403
  - **Response 403**:
    ```json
    {
      "detail": "Tipo de usuario incorrecto para este endpoint",
      "hint": "Este endpoint es solo para workers. Los administradores deben usar /api/auth/login/",
      "user_type_detected": "admin"
    }
    ```
  - **Razón**: Ayudar a frontend/QA a diagnosticar confusión de endpoints
  - **Logging**: Se registra advertencia con IP y email para auditoría
  - **Commit**: `feat: Validar tipo de usuario en worker_login (403 para admins)`

- **[AUTH]** Logging informativo en `/api/auth/login/` si worker lo usa
  - **Comportamiento**: No bloquea login, solo registra advertencia en logs
  - **Log generado**: `⚠️ [ADMIN-LOGIN-WORKER-DETECTED] Worker email@example.com usando /api/auth/login/`
  - **Razón**: Diagnosticar si workers están usando endpoint incorrecto sin bloquearlos
  - **Commit**: `feat: Log informativo cuando worker usa endpoint de admin`

#### Added - API Documentation
- **[DOCS]** Documentación completa de endpoints en `API_ENDPOINTS_DOCUMENTATION.md`
  - **Contenido**:
    - Ejemplos de request/response para todos los endpoints críticos
    - Códigos de error con explicaciones
    - Ejemplos cURL y Python
    - Sección de "Errores comunes y soluciones"
    - Changelog de cambios QA
  - **Formato**: Markdown con ejemplos JSON reales
  - **Audiencia**: QA, Frontend, Nuevos desarrolladores
  - **Commit**: `docs: Agregar documentación completa de API para QA`

#### Added - QA Testing Script
- **[TESTING]** Script de validación `test_qa_support.py`
  - **Valida**:
    1. Password change sin `confirm_password` funciona
    2. Admin en worker endpoint recibe 403 descriptivo
    3. Worker login funciona correctamente
    4. Rutas alias `/api/auth/*` y legacy funcionan
    5. Health check responde
  - **Uso**: `python test_qa_support.py`
  - **Output**: Coloreado con checkmarks verdes/rojos para fácil lectura
  - **Commit**: `test: Agregar script de validación para cambios QA`

### 📊 Evidencia de Testing

#### Test 1: Password Change sin confirm_password
```bash
# Request
POST /api/auth/change-password/
Authorization: Bearer <token>
{
  "current_password": "TempPass123",
  "new_password": "NewSecurePass123!"
}

# Response 200 OK
{
  "detail": "Contraseña actualizada exitosamente",
  "password_change_required": false
}
```

#### Test 2: Admin en Worker Endpoint
```bash
# Request
POST /api/workers/login/
{
  "email": "admin@agriripeness.com",
  "password": "Admin123"
}

# Response 403 Forbidden
{
  "detail": "Tipo de usuario incorrecto para este endpoint",
  "hint": "Este endpoint es solo para workers. Los administradores deben usar /api/auth/login/",
  "user_type_detected": "admin"
}
```

#### Test 3: Worker Login Exitoso
```bash
# Request
POST /api/workers/login/
{
  "email": "worker@agriripeness.com",
  "pin": "1234"
}

# Response 200 OK
{
  "access": "eyJ0eXAi...",
  "refresh": "eyJ0eXAi...",
  "user": {
    "role": "worker",
    "password_change_required": false,
    "pin_configured": true
  }
}
```

### 🔧 Archivos Modificados
- `users/serializers.py`: PasswordChangeSerializer con confirm_password opcional
- `users/views.py`: worker_login con validación de tipo de usuario
- `API_ENDPOINTS_DOCUMENTATION.md`: Documentación completa (nuevo)
- `test_qa_support.py`: Script de validación QA (nuevo)
- `CHANGELOG.md`: Este archivo

### 🏷️ Etiquetas
- `QA-Critical-Fix`
- `Backend-Compatibility`
- `Testing-Support`

---

## [1.1.0] - 2025-11-12

### 🔴 CAMBIOS CRÍTICOS (Breaking Changes)

#### Changed
- **[AUTH]** Login ahora requiere `email` en lugar de `username`
  - **ANTES**: `{"username": "usuario", "password": "..."}`
  - **AHORA**: `{"email": "usuario@ejemplo.com", "password": "..."}`
  - **Razón**: Frontend testing bloqueado - usuarios creados sin username válido
  - **Impacto**: Frontend debe actualizar todos los calls de login
  - **Commit**: `feat: Login con email en vez de username (BREAKING)`

#### Added
- **[AUTH]** Campo `password_change_required` en response de login
  - **Campo**: `user.password_change_required` (boolean)
  - **Uso**: Frontend debe redirigir a `/change-password` si true
  - **Razón**: Forzar cambio de contraseña en primera sesión (admins/workers nuevos)
  - **Commit**: `feat: Agregar password_change_required flag en login response`

- **[PASSWORD]** Campo `password_change_required` en response de cambio de contraseña
  - **Campo**: `password_change_required` (boolean, siempre false después de cambio)
  - **Uso**: Frontend puede verificar que flag se actualizó correctamente
  - **Razón**: Confirmar que usuario ya no está en estado "forzado"
  - **Commit**: `feat: Retornar password_change_required en password-change response`

---

### ✅ MEJORAS (Improvements)

#### Documentation
- **[AUTH]** Docstring profesional agregado a `login()` view
  - Incluye: Request/Response examples, logging levels, frontend actions
  - Formato: Google-style docstrings con sections claras
  - **Commit**: `docs: Agregar docstring profesional a login()`

- **[PASSWORD]** Docstring profesional agregado a `password_change()` view
  - Incluye: Rate limiting info, validations, side effects, security notes
  - Formato: Google-style docstrings con sections claras
  - **Commit**: `docs: Agregar docstring profesional a password_change()`

- **[SERIALIZERS]** Docstring profesional agregado a `LoginSerializer`
  - Incluye: Fields, validation flow, security notes, examples
  - Formato: Google-style docstrings con Args/Returns/Raises
  - **Commit**: `docs: Agregar docstring profesional a LoginSerializer`

- **[SERIALIZERS]** Docstring profesional agregado a `PasswordChangeSerializer`
  - Incluye: Flujo de uso, validations, side effects, security notes
  - Formato: Google-style docstrings con Args/Returns/Raises
  - **Commit**: `docs: Agregar docstring profesional a PasswordChangeSerializer`

#### Logging
- **[AUTH]** Logging estructurado agregado a `login()` view
  - ✅ INFO: Login exitoso con email, rol y flag
  - ⚠️ WARNING: Profile faltante (crea automáticamente)
  - ❌ ERROR: Credenciales inválidas
  - Formato: Emojis para filtrado rápido + contexto detallado
  - **Commit**: `feat: Agregar logging estructurado a login()`

- **[PASSWORD]** Logging estructurado agregado a `password_change()` view
  - ✅ INFO: Contraseña cambiada con email y flag actualizado
  - ⚠️ WARNING: Validación fallida
  - ❌ ERROR: Error inesperado durante cambio
  - Formato: Emojis para filtrado rápido + contexto detallado
  - **Commit**: `feat: Agregar logging estructurado a password_change()`

---

### 🔧 CORRECCIONES (Fixes)

#### Fixed
- **[AUTH]** Login fallaba con 401 para usuarios sin email configurado
  - **Problema**: Django User model usa username, frontend enviaba username vacío
  - **Solución**: LoginSerializer busca usuario por email, autentica con username interno
  - **Impacto**: Login ahora funciona para usuarios creados con solo email
  - **Commit**: `fix: Login con email en LoginSerializer`

- **[AUTH]** Login no retornaba `password_change_required` flag
  - **Problema**: Frontend no sabía si debía forzar cambio de contraseña
  - **Solución**: Agregar flag a response de login desde UserProfile
  - **Impacto**: Frontend puede implementar flujo de cambio forzado
  - **Commit**: `fix: Agregar password_change_required a login response`

- **[PASSWORD]** Endpoint password-change no retornaba flag actualizado
  - **Problema**: Frontend no podía confirmar que flag se actualizó
  - **Solución**: Incluir password_change_required en response (siempre false)
  - **Impacto**: Frontend puede verificar estado actualizado
  - **Commit**: `fix: Retornar password_change_required en password-change response`

---

### 📚 DOCUMENTACIÓN (Documentation)

#### Added
- **[DOCS]** `DEUDA_TECNICA.md` - Documento completo de refactorización pendiente
  - Identifica archivos monolíticos (views.py: 2,782 líneas)
  - Plan de modularización para Sprint 2+
  - Justificación de decisiones de priorización
  - Métricas de mejora objetivo
  - **Razón**: Documentar estado actual y roadmap de mejora
  - **Commit**: `docs: Crear DEUDA_TECNICA.md con plan de refactorización`

- **[DOCS]** `CHANGELOG.md` - Historial de cambios profesional
  - Formato Keep a Changelog
  - Semantic Versioning
  - Categorías: Added, Changed, Fixed, Removed, Security
  - **Razón**: Registro profesional de cambios para equipo y evaluadores
  - **Commit**: `docs: Crear CHANGELOG.md con historial de cambios`

- **[DOCS]** `create_test_users.py` - Script para generar usuarios de testing
  - Crea 3 usuarios: admin con flag, admin normal, worker con flag
  - Documenta credenciales para testing manual
  - Verifica que Profile se crea automáticamente
  - **Razón**: Reproducibilidad de entorno de testing
  - **Commit**: `feat: Agregar script create_test_users.py`

---

### 🔐 SEGURIDAD (Security)

#### Changed
- **[SERIALIZERS]** Password fields marcados como `write_only=True`
  - **Campos**: current_password, new_password, confirm_password, password
  - **Razón**: Evitar que contraseñas aparezcan en responses o logs
  - **Impacto**: Mayor seguridad, passwords nunca en logs
  - **Commit**: `security: Marcar password fields como write_only`

---

## [1.0.0] - 2025-11-10

### Added (Features Previas)
- Sistema de autenticación JWT con refresh tokens
- Gestión de workers con API keys
- Análisis de imágenes con IA (detección de limones)
- Sistema de activación de dispositivos offline
- Admin panel para aprobación de solicitudes
- Email delivery con SendGrid
- Multi-tenancy con organizaciones

---

## Guía de Categorías

### 🔴 CAMBIOS CRÍTICOS (Breaking Changes)
Cambios que rompen compatibilidad con versiones anteriores.
Frontend DEBE actualizar código.

### ✅ MEJORAS (Improvements)
Mejoras no-breaking que agregan valor.
Frontend PUEDE aprovechar pero no es obligatorio.

### 🔧 CORRECCIONES (Fixes)
Correcciones de bugs que no cambian API.
Frontend no requiere cambios.

### 📚 DOCUMENTACIÓN (Documentation)
Cambios solo en documentación.
No afecta código ejecutable.

### 🔐 SEGURIDAD (Security)
Parches de seguridad.
Actualizar INMEDIATAMENTE.

---

## Formato de Commit Messages

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types
- `feat`: Nueva funcionalidad
- `fix`: Corrección de bug
- `docs`: Cambios en documentación
- `refactor`: Refactorización sin cambios funcionales
- `test`: Agregar o modificar tests
- `chore`: Cambios en build, deps, etc.
- `security`: Parche de seguridad

### Scopes
- `auth`: Autenticación (login, register, logout)
- `password`: Gestión de contraseñas
- `workers`: Gestión de workers
- `api-keys`: API keys
- `analysis`: Análisis de imágenes
- `admin`: Panel de administración
- `email`: Email delivery

### Examples
```bash
feat(auth): Login con email en vez de username (BREAKING)
fix(password): Retornar password_change_required en response
docs(auth): Agregar docstring profesional a login()
refactor(views): Dividir views.py en 5 módulos
test(auth): Agregar tests unitarios para login
chore(deps): Actualizar Django a 5.2.7
security(auth): Rate limiting en login endpoint
```

---

## Versionado Semántico

Formato: `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking changes (1.0.0 → 2.0.0)
- **MINOR**: Nuevas features (1.0.0 → 1.1.0)
- **PATCH**: Bug fixes (1.0.0 → 1.0.1)

### Reglas
- Breaking changes → Incrementar MAJOR
- Nuevas features → Incrementar MINOR
- Bug fixes → Incrementar PATCH

---

**Mantenido por**: Rodrigo Freire  
**Última actualización**: 12 Noviembre 2025  
**Formato**: [Keep a Changelog](https://keepachangelog.com/)  
**Versionado**: [Semantic Versioning](https://semver.org/)
