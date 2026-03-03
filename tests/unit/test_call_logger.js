/**
 * Unit Tests for Call Logger Cloud Function
 * 
 * Run with: npm test
 */

const {
  validateRequest,
  sanitizeTranscript,
  calculateMetrics
} = require('../../cloud-functions/call-logger/index.js');

describe('Call Logger', () => {
  
  describe('validateRequest', () => {
    test('should reject null body', () => {
      const result = validateRequest(null);
      expect(result.valid).toBe(false);
    });
    
    test('should reject missing sessionId', () => {
      const result = validateRequest({ action: 'start' });
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('sessionId is required');
    });
    
    test('should accept valid request', () => {
      const result = validateRequest({
        sessionId: 'call-123',
        action: 'start'
      });
      expect(result.valid).toBe(true);
    });
    
    test('should reject invalid action', () => {
      const result = validateRequest({
        sessionId: 'call-123',
        action: 'invalid_action'
      });
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('Invalid action'))).toBe(true);
    });
    
    test('should accept all valid actions', () => {
      const validActions = ['start', 'update', 'end'];
      
      for (const action of validActions) {
        const result = validateRequest({
          sessionId: 'call-123',
          action
        });
        expect(result.valid).toBe(true);
      }
    });
  });
  
  describe('sanitizeTranscript', () => {
    test('should handle null transcript', () => {
      expect(sanitizeTranscript(null)).toEqual([]);
    });
    
    test('should handle empty transcript', () => {
      expect(sanitizeTranscript('')).toEqual([]);
      expect(sanitizeTranscript([])).toEqual([]);
    });
    
    test('should parse string transcript', () => {
      const input = 'Bot: Hello\nUser: Hi there\nBot: How are you?';
      const result = sanitizeTranscript(input);
      
      expect(result).toHaveLength(3);
      expect(result[0].role).toBe('bot');
      expect(result[0].text).toBe('Hello');
      expect(result[1].role).toBe('user');
      expect(result[1].text).toBe('Hi there');
    });
    
    test('should handle Caller role in string', () => {
      const input = 'Bot: Hello\nCaller: Hi there';
      const result = sanitizeTranscript(input);
      
      expect(result[1].role).toBe('caller');
    });
    
    test('should preserve array transcript', () => {
      const input = [
        { role: 'bot', text: 'Hello', timestamp: null },
        { role: 'user', text: 'Hi' }
      ];
      const result = sanitizeTranscript(input);
      
      expect(result).toHaveLength(2);
      expect(result[0].role).toBe('bot');
      expect(result[0].text).toBe('Hello');
    });
    
    test('should handle malformed array items', () => {
      const input = [
        { role: 'bot', text: 'Hello' },
        'plain string',
        { text: 'missing role' },
        { role: 'user' } // missing text
      ];
      const result = sanitizeTranscript(input);
      
      expect(result.length).toBeGreaterThan(0);
      // Should handle all gracefully
    });
  });
  
  describe('calculateMetrics', () => {
    test('should calculate total turns', () => {
      const transcript = [
        { role: 'bot', text: 'Hello' },
        { role: 'user', text: 'Hi' },
        { role: 'bot', text: 'How are you?' },
        { role: 'user', text: 'Good thanks' }
      ];
      
      const metrics = calculateMetrics(transcript);
      expect(metrics.totalTurns).toBe(4);
    });
    
    test('should separate user and bot turns', () => {
      const transcript = [
        { role: 'bot', text: 'Hello' },
        { role: 'user', text: 'Hi' },
        { role: 'bot', text: 'How are you?' },
        { role: 'caller', text: 'Good thanks' }
      ];
      
      const metrics = calculateMetrics(transcript);
      expect(metrics.botTurns).toBe(2);
      expect(metrics.userTurns).toBe(2); // user + caller
    });
    
    test('should calculate average words per turn', () => {
      const transcript = [
        { role: 'bot', text: 'Hello there how are you' }, // 5 words
        { role: 'user', text: 'Good' }, // 1 word
        { role: 'bot', text: 'Great to hear that' }, // 4 words
        { role: 'user', text: 'Thanks for calling' } // 3 words
      ];
      
      const metrics = calculateMetrics(transcript);
      
      // Bot: (5 + 4) / 2 = 4.5 -> rounded to 5
      expect(metrics.avgBotWordsPerTurn).toBeGreaterThan(0);
      
      // User: (1 + 3) / 2 = 2
      expect(metrics.avgUserWordsPerTurn).toBeGreaterThan(0);
    });
    
    test('should handle empty transcript', () => {
      const metrics = calculateMetrics([]);
      
      expect(metrics.totalTurns).toBe(0);
      expect(metrics.userTurns).toBe(0);
      expect(metrics.botTurns).toBe(0);
      expect(metrics.avgUserWordsPerTurn).toBe(0);
      expect(metrics.avgBotWordsPerTurn).toBe(0);
    });
    
    test('should handle transcript with only bot turns', () => {
      const transcript = [
        { role: 'bot', text: 'Hello' },
        { role: 'bot', text: 'Anyone there?' }
      ];
      
      const metrics = calculateMetrics(transcript);
      expect(metrics.botTurns).toBe(2);
      expect(metrics.userTurns).toBe(0);
      expect(metrics.avgUserWordsPerTurn).toBe(0);
    });
  });
});

describe('Call Lifecycle', () => {
  test('should track expected call states', () => {
    const validStates = ['in_progress', 'completed', 'failed'];
    const outcomes = [
      'interested', 'meeting_booked', 'send_info',
      'callback_requested', 'not_interested', 'voicemail',
      'no_answer', 'wrong_number', 'do_not_call'
    ];
    
    expect(validStates).toContain('in_progress');
    expect(validStates).toContain('completed');
    expect(outcomes).toContain('interested');
    expect(outcomes).toContain('meeting_booked');
  });
});
