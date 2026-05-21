class Schedule
	include DataMapper::Resource

	property :id, Serial

	belongs_to :song
end
