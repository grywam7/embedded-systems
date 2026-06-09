class Song
	include DataMapper::Resource

	property :id, Serial
	property :title, String
	property :artist, String
	property :album, String
	property :duration, Integer
  property :is_ready, Boolean, default: false
  
  has n, :schedules

  def duration_string
    "#{duration / 60} m #{duration % 60} s"
  end

  def music_path
    "#{Dir.pwd}/music_data/#{artist} - #{title}.mp3"
  end
end
