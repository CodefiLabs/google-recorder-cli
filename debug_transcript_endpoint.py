#!/usr/bin/env python3
"""
Diagnostic tool to discover the official transcript download endpoint.

This script loads a recording page and logs ALL network requests to help
identify which endpoint the web UI's "Download" button uses for transcripts.

Usage:
    python debug_transcript_endpoint.py <audio_id>

Example:
    python debug_transcript_endpoint.py 80da17b9-29ac-4932-9579-c5bafe0daec9

Instructions:
1. Run this script with the audio_id of a recording with a transcript
2. Wait for the page to load
3. In the browser window that opens, click the overflow menu (three dots)
   next to the transcript pane
4. Click "Download"
5. Check the terminal output to see which requests were made
6. The official transcript endpoint will be logged

The script will print:
- All gRPC PlaybackService endpoints called
- All download URLs accessed
- Request/response details for transcript-related calls
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from playwright.async_api import async_playwright
from recorder_cli.browser import create_context, RECORDER_URL


async def debug_transcript_download(audio_id: str):
    """Load a recording page and log all network activity."""
    print(f"\n{'='*80}")
    print(f"Diagnostic: Finding official transcript download endpoint")
    print(f"Audio ID: {audio_id}")
    print(f"{'='*80}\n")
    
    async with async_playwright() as p:
        context = await create_context(p)
        page = await context.new_page()
        
        # Track all requests
        grpc_calls = []
        download_urls = []
        all_requests = []
        
        def on_request(request):
            all_requests.append({
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type,
            })
            
            # Log gRPC calls
            if "$rpc" in request.url and "PlaybackService" in request.url:
                method = request.url.split("/")[-1]
                grpc_calls.append({
                    "method": method,
                    "url": request.url,
                })
                print(f"[gRPC] {method}")
            
            # Log download URLs
            if "download" in request.url.lower() or "export" in request.url.lower():
                download_urls.append({
                    "method": request.method,
                    "url": request.url,
                })
                print(f"[DOWNLOAD] {request.method} {request.url}")
        
        def on_response(response):
            # Log interesting responses
            if "$rpc" in response.url and "PlaybackService" in response.url:
                method = response.url.split("/")[-1]
                
                async def log_response():
                    try:
                        data = await response.json()
                        
                        # Check if this looks like a transcript
                        is_likely_transcript = False
                        sample = None
                        
                        if isinstance(data, list) and len(data) > 0:
                            if isinstance(data[0], str):
                                sample = data[0][:200] if len(data[0]) > 200 else data[0]
                                is_likely_transcript = (
                                    "[Speaker" in sample or
                                    "Transcribed by Pixel" in sample or
                                    len(data[0]) > 1000
                                )
                        
                        if is_likely_transcript:
                            print(f"\n{'*'*80}")
                            print(f"FOUND POTENTIAL TRANSCRIPT ENDPOINT!")
                            print(f"Method: {method}")
                            print(f"URL: {response.url}")
                            print(f"Response type: {type(data)}")
                            print(f"Sample (first 200 chars):")
                            print(f"{sample}")
                            print(f"{'*'*80}\n")
                    except Exception as e:
                        pass
                
                asyncio.create_task(log_response())
        
        page.on("request", on_request)
        page.on("response", on_response)
        
        print(f"\nNavigating to: {RECORDER_URL}/{audio_id}")
        print("Waiting for page to load...\n")
        
        await page.goto(f"{RECORDER_URL}/{audio_id}")
        
        # Wait for initial page load
        await asyncio.sleep(3)
        
        print(f"\n{'='*80}")
        print("Page loaded. Now:")
        print("1. Click the overflow menu (three dots) next to the transcript")
        print("2. Click 'Download'")
        print("3. Watch the terminal for the endpoint that gets called")
        print("4. Press Ctrl+C when done")
        print(f"{'='*80}\n")
        
        # Keep the browser open for manual interaction
        try:
            await asyncio.sleep(300)  # 5 minutes
        except KeyboardInterrupt:
            print("\n\nStopped by user.")
        
        # Print summary
        print(f"\n\n{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}")
        print(f"\nTotal requests: {len(all_requests)}")
        print(f"gRPC calls to PlaybackService: {len(grpc_calls)}")
        print(f"Download/export URLs: {len(download_urls)}")
        
        if grpc_calls:
            print("\n\nAll gRPC methods called:")
            for call in grpc_calls:
                print(f"  - {call['method']}")
        
        if download_urls:
            print("\n\nAll download/export URLs:")
            for url in download_urls:
                print(f"  - {url['method']} {url['url']}")
        
        await context.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_transcript_endpoint.py <audio_id>")
        print("\nExample:")
        print("  python debug_transcript_endpoint.py 80da17b9-29ac-4932-9579-c5bafe0daec9")
        sys.exit(1)
    
    audio_id = sys.argv[1]
    asyncio.run(debug_transcript_download(audio_id))
