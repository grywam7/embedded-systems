# Background download worker. Verified, still-pending songs are enqueued here
# by POST /song/new and downloaded one at a time off the web request path, so
# the browser gets an instant acknowledgement instead of blocking on spotdl.
#
# A single worker thread is intentional: it serialises downloads (kinder to
# spotdl and to SQLite's single-writer locking).
class DownloadQueueService
  def initialize
    @queue = Thread::Queue.new
    @worker = Thread.new { work_loop }
    @worker.abort_on_exception = false
  end

  def enqueue(song_id, song_url)
    @queue << [song_id, song_url]
  end

  private

  def work_loop
    loop do
      _song_id, _song_url = @queue.pop
      _song = Song.get(_song_id)
      next unless _song

      MusicDownloaderService.new(_song_url).download!(_song)
    rescue StandardError => e
      warn "[download_queue] #{e.full_message}"
    end
  end
end
