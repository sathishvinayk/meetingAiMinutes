#!/usr/bin/env python3
"""Generate protobuf files dynamically"""

import sys
import os

# Add grpc_tools to path
sys.path.insert(0, '/usr/local/lib/python3.10/site-packages')

try:
    from grpc_tools import protoc
    print("✅ grpc_tools found, generating protobuf files...")
    
    result = protoc.main([
        'grpc_tools.protoc',
        '-I./pb',
        '--python_out=.',
        '--grpc_python_out=.',
        './pb/meeting.proto'
    ])
    
    if result == 0:
        print("✅ Protobuf files generated successfully")
        
        # List generated files
        for f in os.listdir('.'):
            if f.startswith('meeting_pb2'):
                print(f"   Generated: {f}")
    else:
        print(f"❌ Protoc failed with exit code: {result}")
        sys.exit(1)
        
except ImportError as e:
    print(f"❌ Failed to import grpc_tools: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error generating protobuf: {e}")
    sys.exit(1)
