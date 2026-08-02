# Tasks — exposição HTTPS do webhook do Instagram

- [ ] 1.1 Túnel com domínio próprio e certificado válido, URL estável
- [ ] 1.2 Expor apenas a rota de webhook; Windmill, Evolution API, Postgres e
      Redis permanecem inacessíveis pela internet
- [ ] 1.3 Token de verificação com entropia adequada
- [ ] 1.4 Procedimento documentado em `DEPLOYMENT.md`
- [ ] 1.5 Aceite (inspeção externa, não teste automatizado): handshake
      respondido de fora da rede local com certificado válido, e portas
      internas confirmadamente fechadas
