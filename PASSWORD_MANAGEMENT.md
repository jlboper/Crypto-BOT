# Contraseña del portal

Implementación preparada; requiere migración 0003 y publicación aprobada antes de estar disponible.

El propietario abre «Cambiar contraseña», introduce su clave actual y confirma una nueva frase de 16 a 128 caracteres. La aplicación local dirige a la misma pantalla del portal HTTPS. El servidor exige sesión, origen exacto, CSRF y reautenticación. El navegador deriva una prueba con PBKDF2-SHA256 de 600000 iteraciones y una sal aleatoria de 256 bits. D1 conserva únicamente SHA-256 de esa prueba, sal y versión de credencial; no guarda la contraseña ni la prueba reutilizable. La prueba se transmite exclusivamente por HTTPS y se trata como una contraseña, nunca como un valor público. Los parámetros de derivación son públicos; la clave inicial aleatoria conserva su mecanismo previo hasta el primer cambio.

Los intentos usan el presupuesto limitado de autenticación. Una transacción condicional evita que dos cambios simultáneos sobrescriban una contraseña sin reautenticación y elimina las sesiones de la versión anterior. La interfaz comprueba longitud y confirmación; el servidor valida formato de prueba y sal. No puede comprobar la complejidad de la frase original porque no la recibe. Ninguna prueba ni contraseña se escribe en almacenamiento del navegador ni logs.

El cambio no modifica Cloudflare, GitHub, OpenAI, la credencial del agente Windows ni las claves de firma. No sincroniza contraseñas personales entre proveedores. Tampoco actualiza el archivo local de acceso inicial: después de cambiar la contraseña, los scripts locales de comprobación que usan esa clave inicial dejarán de iniciar sesión; el agente sigue conectado con su credencial independiente.

## Recuperación y publicación

Si se pierde la contraseña, la recuperación requiere acceso administrativo a Cloudflare: generar una nueva clave aleatoria de 256 bits y rotar OWNER_KEY_HASH por un canal seguro. Al cambiar ese hash, las credenciales y sesiones ligadas a la semilla anterior dejan de ser válidas. No hay recuperación pública ni contraseña universal.

La migración solo añade owner_password; no modifica datos existentes. Aplicarla antes de publicar. La reversión a una versión anterior a esta funcionalidad volvería al mecanismo de clave inicial: después de que el propietario cambie la contraseña, no se debe restaurar esa versión sin rotar también la clave inicial y revisar las sesiones.

Probado con SQLite y workerd/D1 locales: cambio correcto, clave actual incorrecta, CSRF, revocación, conexión del dispositivo, cambios concurrentes, fallo transaccional y recuperación administrativa. Un Worker temporal remoto con datos ficticios confirmó que Cloudflare limita PBKDF2 a 100000 iteraciones, aunque workerd local aceptaba más; ese Worker fue eliminado. Por eso la derivación de 600000 iteraciones se realiza en WebCrypto del navegador y el servidor calcula solo el verificador SHA-256. Queda pendiente la validación visual y de funcionamiento en un navegador real contra el portal publicado; los tests del formulario usan WebCrypto real con un DOM simulado.
