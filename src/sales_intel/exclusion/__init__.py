"""
Capa de exclusión de negocios ya gestionados por Client.

Regla no negociable: estos módulos solo pueden extraer identificadores
mínimos (NIT/matrícula) del CRM interno y de los archivos HUBS. Nunca deben
copiar, exportar ni persistir correo, teléfono, dirección o nombre de
persona/asesor de esas fuentes.
"""
