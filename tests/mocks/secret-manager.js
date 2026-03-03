/**
 * Mock for @google-cloud/secret-manager
 */

const mockSecrets = {
  'sf-username': 'test-sf-user@example.com',
  'sf-password': 'test-password-123',
  'sf-security-token': 'test-security-token',
  'signalwire-project-id': 'test-project-id',
  'signalwire-api-token': 'test-api-token',
  'signalwire-space-url': 'test.signalwire.com',
  'calendar-service-account': JSON.stringify({
    type: 'service_account',
    project_id: 'test-project',
    client_email: 'test@test-project.iam.gserviceaccount.com'
  })
};

class SecretManagerServiceClient {
  async accessSecretVersion(request) {
    const name = request.name;
    const secretName = name.split('/secrets/')[1]?.split('/')[0];
    
    const value = mockSecrets[secretName];
    if (!value) {
      throw new Error(`Secret not found: ${secretName}`);
    }
    
    return [{
      payload: {
        data: Buffer.from(value, 'utf8')
      }
    }];
  }
}

module.exports = { SecretManagerServiceClient };
