// Configuración pública para vista estática; estos endpoints no ejecutan la demo AWS.
// Terraform genera config.js con los valores reales al publicar el frontend.
window.APP_CONFIG = Object.freeze({apiBaseUrl:'https://api.example.invalid',cognitoDomain:'https://auth.example.invalid',clientId:'REEMPLAZAR',redirectUri:'http://127.0.0.1:8766/',scope:'openid email profile ecommerce-agent/access',region:'us-east-1'});
