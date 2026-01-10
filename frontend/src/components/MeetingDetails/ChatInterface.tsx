import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Loader2, X, Link as LinkIcon, ChevronDown, ChevronUp } from 'lucide-react';
import { useSidebar } from '@/components/Sidebar/SidebarProvider';
import { Transcript } from '@/types';
import { MeetingSelector } from './MeetingSelector';

interface Message {
    role: 'user' | 'assistant';
    content: string;
}

interface ChatInterfaceProps {
    meetingId: string;
    onClose: () => void;
    currentTranscripts?: Transcript[];
}

export function ChatInterface({ meetingId, onClose, currentTranscripts }: ChatInterfaceProps) {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const { serverAddress } = useSidebar();

    // Scoped Search State
    const [showLinkContext, setShowLinkContext] = useState(false);
    const [linkedMeetingIds, setLinkedMeetingIds] = useState<string[]>([]);

    // Construct context from live transcripts if available
    const getContextFromTranscripts = () => {
        if (!currentTranscripts || currentTranscripts.length === 0) return undefined;
        return currentTranscripts.map(t => `[${t.timestamp}] ${t.text}`).join('\n');
    };

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    // State for model config
    const [modelConfig, setModelConfig] = useState<{ provider: string, model: string } | null>(null);

    // Fetch model config on mount
    useEffect(() => {
        const fetchConfig = async () => {
            try {
                const res = await fetch(`${serverAddress}/get-model-config`);
                if (res.ok) {
                    const config = await res.json();
                    setModelConfig(config);
                }
            } catch (e) {
                console.error("Failed to fetch model config", e);
            }
        };
        fetchConfig();
    }, [serverAddress]);


    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!input.trim() || isLoading) return;

        const userMessage = input.trim();
        setInput('');
        setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
        setIsLoading(true);

        try {
            // Create a placeholder for the AI response
            setMessages(prev => [...prev, { role: 'assistant', content: '' }]);

            // Use configured model or default to Gemini Flash
            const provider = modelConfig?.provider || 'gemini';
            const modelName = modelConfig?.model || 'gemini-3-flash-preview';

            const contextText = getContextFromTranscripts();

            const response = await fetch(`${serverAddress}/chat-meeting`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    meeting_id: meetingId,
                    question: userMessage,
                    model: provider,
                    model_name: modelName,
                    context_text: contextText || "",
                    allowed_meeting_ids: linkedMeetingIds.length > 0 ? linkedMeetingIds : undefined,
                    history: messages.slice(-10).map(m => ({
                        role: m.role,
                        content: m.content.slice(0, 500)
                    }))
                }),
            });

            if (!response.ok) {
                throw new Error(`Request failed: ${response.status}`);
            }

            if (!response.body) throw new Error('No response body');

            const reader = response.body.getReader();

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = new TextDecoder().decode(value);
                setMessages(prev => {
                    const newMessages = [...prev];
                    const lastMessage = newMessages[newMessages.length - 1];
                    if (lastMessage.role === 'assistant') {
                        lastMessage.content += chunk;
                    }
                    return newMessages;
                });
            }
        } catch (error) {
            console.error('Chat error:', error);
            setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error while processing your request.' }]);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="flex flex-col h-full bg-white dark:bg-zinc-900 border-l border-zinc-200 dark:border-zinc-800 w-[400px] shadow-xl fixed right-0 top-0 bottom-0 z-50">
            {/* Header */}
            <div className="flex flex-col border-b border-zinc-200 dark:border-zinc-800">
                <div className="flex items-center justify-between p-4 pb-2">
                    <h3 className="font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                        <Bot className="w-5 h-5 text-blue-500" />
                        Ask AI
                    </h3>
                    <div className="flex items-center gap-1">
                        <button
                            onClick={() => setShowLinkContext(!showLinkContext)}
                            className={`
                                flex items-center gap-1.5 px-2 py-1 text-xs font-medium rounded-full transition-colors
                                ${linkedMeetingIds.length > 0
                                    ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300'
                                    : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700'}
                            `}
                        >
                            <LinkIcon className="w-3 h-3" />
                            {linkedMeetingIds.length > 0 ? `${linkedMeetingIds.length} Linked` : 'Link Context'}
                            {showLinkContext ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                        </button>
                        <button
                            onClick={onClose}
                            className="p-1 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-full transition-colors ml-1"
                        >
                            <X className="w-5 h-5 text-zinc-500" />
                        </button>
                    </div>
                </div>

                {/* Context Linker Dropdown */}
                {showLinkContext && (
                    <div className="border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50">
                        <MeetingSelector
                            selectedIds={linkedMeetingIds}
                            onSelectionChange={setLinkedMeetingIds}
                        />
                    </div>
                )}
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.length === 0 && (
                    <div className="text-center text-zinc-500 mt-10 space-y-2">
                        <Bot className="w-12 h-12 mx-auto opacity-20" />
                        <p>Ask anything about this meeting!</p>
                        {linkedMeetingIds.length > 0 && (
                            <p className="text-xs text-blue-500 font-medium">
                                Searching {linkedMeetingIds.length} linked meeting(s)
                            </p>
                        )}
                        <p className="text-xs text-zinc-400">"What were the key decisions?"</p>
                    </div>
                )}

                {messages.map((msg, idx) => (
                    <div
                        key={idx}
                        className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
                    >
                        <div className={`
              w-8 h-8 rounded-full flex items-center justify-center shrink-0
              ${msg.role === 'user' ? 'bg-blue-100 text-blue-600' : 'bg-green-100 text-green-600'}
            `}>
                            {msg.role === 'user' ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                        </div>
                        <div className={`
              rounded-lg p-3 max-w-[85%] text-sm whitespace-pre-wrap
              ${msg.role === 'user'
                                ? 'bg-blue-500 text-white'
                                : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200'}
            `}>
                            {msg.role === 'assistant' ? (
                                <div>
                                    {msg.content.split('\n').map((line, i) => {
                                        // Pattern: [Source: Meeting Name (Date)]
                                        const citationMatch = line.match(/^\[Source: (.*?) \((.*?)\)\]/);
                                        if (citationMatch) {
                                            return (
                                                <div key={i} className="flex items-center gap-1.5 mt-2 mb-1 text-xs text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 px-2 py-1 rounded w-fit border border-blue-100 dark:border-blue-800">
                                                    <span className="font-semibold">Source:</span>
                                                    <span>{citationMatch[1]}</span>
                                                    <span className="opacity-75">({citationMatch[2]})</span>
                                                </div>
                                            );
                                        }
                                        return <div key={i} className="min-h-[1.2em]">{line}</div>;
                                    })}
                                </div>
                            ) : (
                                msg.content
                            )}
                        </div>
                    </div>
                ))}
                <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <form onSubmit={handleSubmit} className="p-4 border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
                <div className="relative">
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="Ask a question..."
                        className="w-full pl-4 pr-10 py-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-transparent focus:outline-none focus:ring-2 focus:ring-blue-500 dark:text-zinc-100"
                        disabled={isLoading}
                    />
                    <button
                        type="submit"
                        disabled={!input.trim() || isLoading}
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-blue-500 hover:text-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                    </button>
                </div>
            </form>
        </div>
    );
}
