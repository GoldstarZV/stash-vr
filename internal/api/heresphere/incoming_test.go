package heresphere

import (
	"context"
	"testing"

	"stash-vr/internal/util"
)

func markerNames(in incomingTags) []string {
	out := make([]string, len(in.markers))
	for i, m := range in.markers {
		out[i] = m.PrimaryTagName + "=" + m.MarkerId
	}
	return out
}

func TestClassify_UntimedUnknownTagIsIgnored(t *testing.T) {
	in := classifyIncomingTags(context.Background(), []tagDto{{Name: "Something:else"}})

	if len(in.markers) != 0 || len(in.tags) != 0 {
		t.Fatalf("untimed unknown tag must create nothing, got %+v", in)
	}
}

func TestClassify_LegacyLegendIsIgnoredEvenWhenTimed(t *testing.T) {
	end := 5000.0
	in := classifyIncomingTags(context.Background(), []tagDto{
		{Name: "P:3", Start: 100, End: &end},
		{Name: "movie:Some Movie", Start: 100, End: &end},
		{Name: "Org:true", Start: 0.1, End: &end},
	})

	if len(in.markers) != 0 {
		t.Fatalf("legacy legends must never become markers, got %v", markerNames(in))
	}
}

func TestClassify_TimedUnknownTagBecomesNewMarker(t *testing.T) {
	end := 30000.0
	in := classifyIncomingTags(context.Background(), []tagDto{{Name: "Kiss:opening", Start: 12000, End: &end}})

	if len(in.markers) != 1 {
		t.Fatalf("expected one marker, got %v", markerNames(in))
	}
	m := in.markers[0]
	if m.PrimaryTagName != "Kiss" || m.Title != "opening" || m.MarkerId != "0" || m.StartSecond != 12 || m.EndSecond == nil || *m.EndSecond != 30 {
		t.Fatalf("unexpected marker %+v", m)
	}
}

func TestClassify_ExistingMarkerKeepsItsId(t *testing.T) {
	in := classifyIncomingTags(context.Background(), []tagDto{{Name: "Kiss", Start: 12000, Rating: util.Ptr(float32(42))}})

	if len(in.markers) != 1 || in.markers[0].MarkerId != "42" {
		t.Fatalf("expected marker id 42, got %v", markerNames(in))
	}
}

func TestClassify_ExistingMarkerAtZeroWithoutEndIsKept(t *testing.T) {
	// A marker at second 0 with no end comes back as Start 0, End nil; the id
	// in Rating must keep it, otherwise UpdateMarkers would destroy it.
	in := classifyIncomingTags(context.Background(), []tagDto{{Name: "Intro", Start: 0, Rating: util.Ptr(float32(7))}})

	if len(in.markers) != 1 || in.markers[0].MarkerId != "7" || in.markers[0].StartSecond != 0 {
		t.Fatalf("expected marker id 7 at 0s, got %v", markerNames(in))
	}
}

func TestClassify_HiddenAndKnownLegendsAreNotMarkers(t *testing.T) {
	minus := -1.0
	in := classifyIncomingTags(context.Background(), []tagDto{
		{Name: "@:Some Performer", Start: -1, End: &minus},
		{Name: "Played:3"},
		{Name: "#:newtag"},
		{Name: "/o"},
	})

	if len(in.markers) != 0 {
		t.Fatalf("expected no markers, got %v", markerNames(in))
	}
	if !in.hasPlayCount || len(in.tags) != 1 || in.tags[0] != "newtag" || len(in.commands) != 1 || in.commands[0] != "/o" {
		t.Fatalf("classification wrong: %+v", in)
	}
}

func TestClassify_MarkerNamedLikeALegendKeepsItsId(t *testing.T) {
	// Markers whose primary tag is a legend or legacy word ("O", "Studio")
	// still carry their id in Rating and must not be dropped, since
	// UpdateMarkers destroys every marker missing from the incoming list.
	end := 9000.0
	in := classifyIncomingTags(context.Background(), []tagDto{
		{Name: "O", Start: 4000, End: &end, Rating: util.Ptr(float32(5))},
		{Name: "Studio:intro", Start: 0, Rating: util.Ptr(float32(6))},
		{Name: "Played:3"},
	})

	if got := markerNames(in); len(got) != 2 || got[0] != "O=5" || got[1] != "Studio=6" {
		t.Fatalf("expected markers O=5 and Studio=6, got %v", got)
	}
	if !in.hasPlayCount {
		t.Fatal("untagged legend must still be classified as metadata")
	}
}

func TestClassify_HashMarkers(t *testing.T) {
	for _, tc := range []struct {
		name               string
		tag                tagDto
		primary, title, id string
	}{
		{"new titled marker", tagDto{Name: "##marker:TESTZ", Start: 12000, End: util.Ptr(30000.0)}, "##marker", "TESTZ", "0"},
		{"new point marker", tagDto{Name: "#MVR", Start: 15000}, "#MVR", "", "0"},
		{"point at zero", tagDto{Name: "#MVR"}, "#MVR", "", "0"},
		{"zero rating", tagDto{Name: "##marker:TESTZ", Start: 12000, Rating: util.Ptr(float32(0))}, "##marker", "TESTZ", "0"},
		{"existing marker", tagDto{Name: "##marker:TESTZ", Start: 12000, Rating: util.Ptr(float32(42))}, "##marker", "TESTZ", "42"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			in := classifyIncomingTags(context.Background(), []tagDto{tc.tag})
			if len(in.markers) != 1 || len(in.tags) != 0 {
				t.Fatalf("expected only one marker, got %+v", in)
			}
			m := in.markers[0]
			if m.PrimaryTagName != tc.primary || m.Title != tc.title || m.MarkerId != tc.id || m.StartSecond != tc.tag.Start/1000 {
				t.Fatalf("unexpected marker %+v", m)
			}
			if tc.tag.End == nil {
				if m.EndSecond != nil {
					t.Fatal("point marker acquired an end time")
				}
			} else if m.EndSecond == nil || *m.EndSecond != *tc.tag.End/1000 {
				t.Fatalf("incorrect end time: %+v", m.EndSecond)
			}
		})
	}
}

func TestClassify_HashSceneTagsAndHiddenHierarchy(t *testing.T) {
	in := classifyIncomingTags(context.Background(), []tagDto{
		{Name: "#:#Boy/Girl"},
		{Name: "#:vr"},
		{Name: "#Category:vr", Start: -1, End: util.Ptr(-1.0)},
		{Name: "#:#Category", Start: -1, End: util.Ptr(-1.0)},
		{Name: "##marker:hidden", Start: -1, End: util.Ptr(-1.0)},
		{Name: "#:"},
	})
	if len(in.markers) != 0 || len(in.tags) != 2 || in.tags[0] != "#Boy/Girl" || in.tags[1] != "vr" {
		t.Fatalf("visible scene tags must survive without promoting hidden hierarchy tags: %+v", in)
	}
}

func TestClassify_Issue94MetadataWithZeroRating(t *testing.T) {
	// HereSphere may include rating:0 on new tags. Zero is not a Stash
	// marker ID and must not bypass metadata classification.
	for _, rating := range []*float32{nil, util.Ptr(float32(0))} {
		in := classifyIncomingTags(context.Background(), []tagDto{
			{Name: "P:37", Start: 0, End: util.Ptr(903000.0), Rating: rating},
			{Name: "P:38", Start: 0, End: util.Ptr(3613000.0), Rating: rating},
			{Name: "P:39", Start: 0, End: util.Ptr(3613000.0), Rating: rating},
			{Name: "O:0", Start: 903000, End: util.Ptr(1806000.0), Rating: rating},
			{Name: "Org:false", Start: 1806000, End: util.Ptr(2710000.0), Rating: rating},
			{Name: "movie:movie", Start: 2710000, End: util.Ptr(3613000.0), Rating: rating},
			{Name: "Performer:Example", Start: 1, End: util.Ptr(3613000.0), Rating: rating},
			{Name: "@:Example", Rating: rating},
			{Name: "Played:39", Rating: rating},
			{Name: "O-Count:0", Rating: rating},
			{Name: "Organized:false", Rating: rating},
			{Name: "Rating:80", Rating: rating},
			{Name: "#:vr", Rating: rating},
			{Name: "#Category:vr", Start: -1, End: util.Ptr(-1.0), Rating: rating},
		})
		if len(in.markers) != 0 || len(in.tags) != 1 || in.tags[0] != "vr" || !in.hasPlayCount || !in.hasOCount || !in.hasOrganized || !in.hasRating {
			t.Fatalf("metadata with rating %v was misclassified: %+v", rating, in)
		}
	}
}
